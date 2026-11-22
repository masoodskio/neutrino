#include <stdint.h>
#include <intrman.h>
#include <loadcore.h>
#include <sifcmd.h>
#include <stdio.h>
#include <sysclib.h>
#include <thbase.h>
#include <thsemap.h>
#include "smap.h"
#include "ioplib.h"
#include "adapter.h"

#define FRAME_MAX 1536u
struct descriptor { uint32_t kind,flags; const char *vendor,*description,*name; };
struct endpoints {
    uint32_t device_id,iop_out_cmd,iop_ready_cmd,iop_control_rpc;
    uint32_t ee_in_cmd,ee_ready_cmd,ee_state_rpc,iop_buffer,ee_buffer;
};
struct command { uint32_t header[4],route; int32_t value; uint32_t reserved[2]; };
struct packet { uint32_t bytes; uint8_t frame[FRAME_MAX]; };
typedef char descriptor_size[sizeof(struct descriptor)==20?1:-1];
typedef char endpoints_size[sizeof(struct endpoints)==36?1:-1];
typedef char command_size[sizeof(struct command)==32?1:-1];
static struct descriptor desc={1,3,"SCE","Ethernet (Network Adaptor)","smap"};
static struct endpoints ep;
static int (*d_register)(struct descriptor *,struct endpoints *,int);
static int (*d_buffers)(struct descriptor *,struct endpoints *);
static int (*d_unregister)(struct descriptor *,struct endpoints *);
static int (*d_add)(uint32_t,void (*)(void *,void *),void *);
static int (*d_remove)(uint32_t);
static int (*d_send)(int,uint32_t,struct command *,int,void *,void *,int);
static void (*d_bind)(SifRpcClientData_t *,int,int);
static void (*d_call)(SifRpcClientData_t *,int,int,void *,int,void *,int,SifRpcEndFunc_t,void *);
static int (*d_wait)(int,int (*)(void));
/* Keep all server operations on the same runtime sifcmd export table. */
static __typeof__(&sceSifSetRpcQueue) runtime_set_queue;
static __typeof__(&sceSifRegisterRpc) runtime_register;
static __typeof__(&sceSifRpcLoop) runtime_loop;
static __typeof__(&sceSifRemoveRpc) runtime_remove;
static __typeof__(&sceSifRemoveRpcQueue) runtime_remove_queue;
static SifRpcClientData_t client __attribute__((aligned(16)));
static SifRpcServerData_t server;
static SifRpcDataQueue_t rpc_queue;
static uint32_t rpc_buffer[256] __attribute__((aligned(16)));
static uint32_t state_buffer[4] __attribute__((aligned(16)));
static struct packet ee_tx __attribute__((aligned(16)));
static struct packet to_ee __attribute__((aligned(16)));
static struct command ready_cmd __attribute__((aligned(16)));
static struct command frame_cmd __attribute__((aligned(16)));
static uint32_t rx_scratch[FRAME_MAX/4u] __attribute__((aligned(16)));
static struct packet rx_ring[2];
static unsigned head,tail,count;
static volatile int active,loaded,terminating,epoch,control_pending,tx_pending;
static int rx_credit=-1,rpc_up=-1,worker_id=-1,rpc_id=-1;
static int registered,claimed,tx_handler,credit_handler;
static uint32_t rx_dropped,tx_errors;
static int lock(void) { int state; CpuSuspendIntr(&state); return state; }
static void unlock(int state) { CpuResumeIntr(state); }
static void clear_queue(void) { int s=lock(); head=tail=count=0; ++epoch; unlock(s); }
static uint32_t media_from_smap(uint8_t mode)
{
    uint32_t v=(mode&12u)?6u:3u;
    v|=(mode&10u)?0x00100000u:0x00200000u;
    if(mode&64u) v|=0x00400000u;
    return v;
}
static int multicast_hash(const void *request,unsigned bytes,uint32_t hash[4])
{
    const uint8_t *p=request; int32_t n; unsigned i,j,b;
    uint32_t bins[4]={0,0,0,0};
    if(!request || bytes<4u) return -1;
    memcpy(&n,p,4);
    if(n>0 && (uint32_t)n>(bytes-4u)/6u) return -1;
    if(n==0) for(i=0;i<4u;++i) bins[i]=0xffffu;
    if(n>0) for(i=0;i<(unsigned)n;++i) {
        uint32_t crc=0xffffffffu;
        for(j=0;j<6u;++j) {
            uint8_t c=p[4u+i*6u+j];
            for(b=0;b<8u;++b) {
                uint32_t bit=(crc>>31)^(c&1u); crc<<=1;
                if(bit) crc^=0x04c11db7u;
                c>>=1;
            }
        }
        crc>>=26; bins[crc>>4]|=1u<<(crc&15u);
    }
    for(i=0;i<4u;++i) hash[i]=bins[3u-i];
    return 0;
}
static int receive_frame(uint16_t n,const uint8_t *hdr,uint16_t hdr_n)
{
    int s,stamp; (void)hdr; (void)hdr_n;
    s=lock(); stamp=epoch;
    if(!active || terminating || count==2u || n<14u || n>FRAME_MAX) {
        ++rx_dropped; unlock(s); return -1;
    }
    unlock(s);
    smap_fifo_read(0,rx_scratch,((unsigned)n+3u)&~3u);
    s=lock();
    if(!active || terminating || stamp!=epoch || count==2u) {
        ++rx_dropped; unlock(s); return -1;
    }
    rx_ring[tail].bytes=n; memcpy(rx_ring[tail].frame,rx_scratch,n);
    tail=(tail+1u)%2u; ++count; unlock(s); return 0;
}
static void outgoing_command(void *packet,void *arg)
{ (void)packet; (void)arg; tx_pending=1; }
static void credit_command(void *packet,void *arg)
{
    struct command *cmd=packet; (void)arg;
    if(cmd->value>0) iSignalSema(rx_credit); else PollSema(rx_credit);
}
static int terminated(void) { active=0; terminating=1; ++epoch; return 0; }
static void ready(int value)
{
    ready_cmd.value=value;
    d_send(0,ep.ee_ready_cmd,&ready_cmd,sizeof(ready_cmd),0,0,0);
}
static void notify(int fn,uint32_t value)
{
    memset(state_buffer,0,sizeof(state_buffer)); state_buffer[0]=value;
    d_call(&client,fn,0,state_buffer,4,state_buffer,4,0,0);
}
static void *control(int fn,void *buf,int bytes)
{
    uint32_t value,hash[4];
    if(bytes<0 || bytes>(int)sizeof(rpc_buffer) || (bytes>0 && !buf)) return buf;
    value=0;
    if(bytes==0) {
        if(fn!=1 && fn!=2) return buf;
        if(!buf) buf=rpc_buffer;
    } else {
        if(bytes<4) return buf;
        memcpy(&value,buf,4);
    }
    switch(fn) {
    case 1:
        clear_queue(); tx_pending=0; active=1; control_pending|=1;
        value=0; memcpy(buf,&value,4); break;
    case 2:
        active=0; clear_queue(); tx_pending=0; control_pending|=1;
        value=0; memcpy(buf,&value,4); break;
    case 4:
        /* Keep the shared PHY configuration; report its actual media later. */
        control_pending|=2; break;
    case 5:
        if(multicast_hash(buf,(unsigned)bytes,hash)<0) {
            value=(uint32_t)-1; memcpy(buf,&value,4);
        } else smap_set_multicast_hash(hash);
        break;
    default:
        value=(uint32_t)-1; memcpy(buf,&value,4); break;
    }
    return buf;
}
static void rpc_thread(void *arg)
{
    (void)arg;
    runtime_set_queue(&rpc_queue,GetThreadId());
    runtime_register(&server,(int)ep.iop_control_rpc,control,rpc_buffer,0,0,&rpc_queue);
    SignalSema(rpc_up); runtime_loop(&rpc_queue); ExitThread();
}
static int thread(void (*entry)(void *),int priority)
{
    iop_thread_t t; int id,r;
    memset(&t,0,sizeof(t)); t.attr=TH_C; t.thread=entry; t.priority=priority; t.stacksize=4096;
    id=CreateThread(&t); if(id<0) return id;
    r=StartThread(id,0);
    if(r<0) { DeleteThread(id); return r; }
    return id;
}
static int sema(void)
{
    iop_sema_t s; memset(&s,0,sizeof(s)); s.initial=0; s.max=1; return CreateSema(&s);
}
static int resolve(void)
{
    iop_library_t *lib=ioplib_getByName("ent_devm"); unsigned i;
    if(!lib || lib->version!=0x0101 || ioplib_getTableSize(lib)<14u) return -1;
    for(i=4;i<=13u;++i) if(!lib->exports[i]) return -1;
    d_register=(void *)lib->exports[4]; d_buffers=(void *)lib->exports[5];
    d_unregister=(void *)lib->exports[6]; d_add=(void *)lib->exports[7];
    d_remove=(void *)lib->exports[8]; d_send=(void *)lib->exports[9];
    d_bind=(void *)lib->exports[10]; d_call=(void *)lib->exports[11];
    d_wait=(void *)lib->exports[12];
    lib=ioplib_getByName("sifcmd\0");
    if(!lib || ioplib_getTableSize(lib)<=25u || !lib->exports[17] ||
       !lib->exports[19] || !lib->exports[22] || !lib->exports[24] || !lib->exports[25]) return -1;
    runtime_register=(__typeof__(runtime_register))lib->exports[17];
    runtime_set_queue=(__typeof__(runtime_set_queue))lib->exports[19];
    runtime_loop=(__typeof__(runtime_loop))lib->exports[22];
    runtime_remove=(__typeof__(runtime_remove))lib->exports[24];
    runtime_remove_queue=(__typeof__(runtime_remove_queue))lib->exports[25];
    return 0;
}
static void transmit_one(void)
{
    unsigned n; int r;
    if(!active || !tx_pending) return;
    tx_pending=0; n=ee_tx.bytes;
    if(n<14u || n>FRAME_MAX) { ++tx_errors; ready(active?1:0); return; }
    r=smap_transmit(ee_tx.frame,(uint16_t)n,0,0);
    if(r<0) ++tx_errors;
    ready(active?1:0);
}
static void receive_one(void)
{
    unsigned n,padded; int s;
    if(!active || PollSema(rx_credit)<0) return;
    s=lock();
    if(!count || !active) { unlock(s); SignalSema(rx_credit); return; }
    n=rx_ring[head].bytes;
    memset(&to_ee,0,sizeof(to_ee)); to_ee.bytes=n;
    memcpy(to_ee.frame,rx_ring[head].frame,n);
    head=(head+1u)%2u; --count; unlock(s);
    if(n<14u || n>FRAME_MAX || !ep.ee_buffer) {
        ++rx_dropped; SignalSema(rx_credit); return;
    }
    padded=(n+7u)&~3u;
    d_send(0,ep.ee_in_cmd,&frame_cmd,sizeof(frame_cmd),&to_ee,
        (void *)(uintptr_t)ep.ee_buffer,(int)padded);
}
static void worker(void *arg)
{
    unsigned tick=0; uint32_t old_state=0xffffffffu,old_media=0xffffffffu;
    uint8_t link,mode; int pending,s; (void)arg;
    if(d_wait((int)desc.kind,terminated)<0 || terminating) goto done;
    ep.iop_buffer=(uint32_t)(uintptr_t)&ee_tx;
    if(d_register(&desc,&ep,0)<0 || terminating) goto done;
    registered=1;
    d_bind(&client,(int)ep.ee_state_rpc,0); if(!client.server) goto done;
    memset(state_buffer,0,sizeof(state_buffer));
    d_call(&client,0,0,state_buffer,4,state_buffer,0,0,0);
    memset(state_buffer,0,sizeof(state_buffer)); SMAPGetMACAddress((uint8_t *)state_buffer);
    d_call(&client,1,0,state_buffer,8,state_buffer,4,0,0);
    if(d_add(ep.iop_out_cmd,outgoing_command,0)<0) goto done;
    tx_handler=1;
    if(d_add(ep.iop_ready_cmd,credit_command,0)<0) goto done;
    credit_handler=1;
    rpc_id=thread(rpc_thread,16); if(rpc_id<0) goto done; WaitSema(rpc_up);
    if(d_buffers(&desc,&ep)<0 || !ep.ee_buffer || terminating) goto done;
    while(!terminating) {
        s=lock(); pending=control_pending; control_pending=0; unlock(s);
        if(pending&1) ready(active?1:0);
        transmit_one(); receive_one();
        if(++tick>=1000u || (pending&2)) {
            uint32_t state,media; tick=0; smap_get_link_status(&link,&mode);
            state=link?3u:2u; media=media_from_smap(mode);
            if(state!=old_state) { notify(2,state); old_state=state; }
            if(media!=old_media) { notify(3,media); old_media=media; }
        }
        DelayThread(1000);
    }
done:
    if(!terminating) printf("smap_eenet: adapter initialization failed\n");
    active=0; terminating=1; clear_queue();
    if(claimed) { smap_release_game_rx_callback(receive_frame); claimed=0; }
    if(tx_handler) { d_remove(ep.iop_out_cmd); tx_handler=0; }
    if(credit_handler) { d_remove(ep.iop_ready_cmd); credit_handler=0; }
    if(rpc_id>=0) {
        runtime_remove(&server,&rpc_queue); runtime_remove_queue(&rpc_queue);
        TerminateThread(rpc_id); DeleteThread(rpc_id); rpc_id=-1;
    }
    if(registered) { d_unregister(&desc,&ep); registered=0; }
    ExitThread();
}
int eent_loaded(void) { return loaded; }
int eent_launch(void)
{
    int r;
    if(loaded) return terminating?-1:0;
    if(resolve()<0) { printf("smap_eenet: required network exports unavailable\n"); return -1; }
    rx_credit=sema(); if(rx_credit<0) return rx_credit;
    rpc_up=sema(); if(rpc_up<0) { DeleteSema(rx_credit); return rpc_up; }
    r=smap_claim_game_rx_callback(receive_frame);
    if(r<0) { DeleteSema(rx_credit); DeleteSema(rpc_up); return r; }
    claimed=1; worker_id=thread(worker,18);
    if(worker_id<0) {
        smap_release_game_rx_callback(receive_frame); claimed=0;
        DeleteSema(rx_credit); DeleteSema(rpc_up); return worker_id;
    }
    loaded=1; return 0;
}
