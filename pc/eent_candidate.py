#!/usr/bin/env python3
"""Experimental EENET source bundle. Not hardware-validated.
Generate into a disposable build checkout with --apply; --check writes nothing.
The source is inline and reviewable; no binaries or external downloads are used.
The game-facing ABI is reconstructed from the supplied Battlefront II modules.
Stop/unload and repeated network-stack entry are not supported by this prototype.
"""
from pathlib import Path
import re
import sys

NEW = {}
NEW['iop/smap_eenet/Makefile'] = '''IOP_CFLAGS += -DDEBUG -I../smap/include -I../smap_inet/src
IOP_OBJS = main.o adapter.o ioplib.o imports.o
IOP_OBJS_DIR = obj/
IOP_BIN = smap_eenet.irx
include ../Rules.make
'''
NEW['iop/smap_eenet/src/ioplib.c'] = '#include "../../smap_inet/src/ioplib.c"\n'.replace('\n','
')
NEW['iop/smap_eenet/src/irx_imports.h'] = '''#include <irx.h>
#include <intrman.h>
#include <loadcore.h>
#include <stdio.h>
#include <sysclib.h>
#include <thbase.h>
#include <thsemap.h>
#include <sifcmd.h>
#include "smap.h"
'''
NEW['iop/smap_eenet/src/imports.lst'] = '''intrman_IMPORTS_start
I_CpuSuspendIntr
I_CpuResumeIntr
intrman_IMPORTS_end
loadcore_IMPORTS_start
I_GetLoadcoreInternalData
loadcore_IMPORTS_end
stdio_IMPORTS_start
I_printf
stdio_IMPORTS_end
sysclib_IMPORTS_start
I_memcpy
I_memset
I_strcpy
I_strcmp
I_strstr
sysclib_IMPORTS_end
thbase_IMPORTS_start
I_CreateThread
I_DeleteThread
I_StartThread
I_ExitThread
I_TerminateThread
I_GetThreadId
I_DelayThread
thbase_IMPORTS_end
thsemap_IMPORTS_start
I_CreateSema
I_DeleteSema
I_SignalSema
I_iSignalSema
I_WaitSema
I_PollSema
thsemap_IMPORTS_end
sifcmd_IMPORTS_start
I_sceSifSetRpcQueue
I_sceSifRegisterRpc
I_sceSifRpcLoop
I_sceSifRemoveRpc
I_sceSifRemoveRpcQueue
sifcmd_IMPORTS_end
smap_IMPORTS_start
I_SMAPGetMACAddress
I_smap_transmit
I_smap_fifo_read
I_smap_get_link_status
I_smap_set_multicast_hash
I_smap_claim_game_rx_callback
I_smap_release_game_rx_callback
smap_IMPORTS_end
'''
NEW['iop/smap_eenet/src/adapter.h'] = '''#ifndef EENT_ADAPTER_H
#define EENT_ADAPTER_H
int eent_launch(void);
int eent_loaded(void);
#endif
'''
NEW['iop/smap_eenet/src/adapter.c'] = r'''#include <stdint.h>
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
                if(bit) crc^=0x04c11db7u; c>>=1;
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
    if(bytes<4 || bytes>(int)sizeof(rpc_buffer)) return buf;
    memcpy(&value,buf,4);
    switch(fn) {
    case 1:
        clear_queue(); tx_pending=0; active=1; control_pending|=1;
        value=0; memcpy(buf,&value,4); break;
    case 2:
        active=0; clear_queue(); tx_pending=0; control_pending|=1;
        value=0; memcpy(buf,&value,4); break;
    case 4:
        control_pending|=2;
        printf("EENT requested media=%08x; retaining shared PHY\\n",(unsigned)value); break;
    case 5:
        if(multicast_hash(buf,(unsigned)bytes,hash)<0) {
            value=(uint32_t)-1; memcpy(buf,&value,4);
        } else smap_set_multicast_hash(hash);
        break;
    default:
        printf("EENT unsupported control=%d length=%d\\n",fn,bytes);
        value=(uint32_t)-1; memcpy(buf,&value,4); break;
    }
    return buf;
}
static void rpc_thread(void *arg)
{
    (void)arg;
    sceSifSetRpcQueue(&rpc_queue,GetThreadId());
    sceSifRegisterRpc(&server,(int)ep.iop_control_rpc,control,rpc_buffer,0,0,&rpc_queue);
    SignalSema(rpc_up); sceSifRpcLoop(&rpc_queue); ExitThread();
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
    d_wait=(void *)lib->exports[12]; return 0;
}
static void transmit_one(void)
{
    unsigned n; int r;
    if(!active || !tx_pending) return;
    tx_pending=0; n=ee_tx.bytes;
    if(n<14u || n>FRAME_MAX) { ++tx_errors; ready(active?1:0); return; }
    r=smap_transmit(ee_tx.frame,(uint16_t)n,0,0);
    if(r<0) ++tx_errors; ready(active?1:0);
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
    printf("EENT waiting for game registration\\n");
    if(d_wait((int)desc.kind,terminated)<0 || terminating) goto done;
    ep.iop_buffer=(uint32_t)(uintptr_t)&ee_tx;
    if(d_register(&desc,&ep,0)<0 || terminating) goto done;
    registered=1;
    printf("EENT registered device=%u ctl=%08x ee=%08x\\n",(unsigned)ep.device_id,
        (unsigned)ep.iop_control_rpc,(unsigned)ep.ee_state_rpc);
    d_bind(&client,(int)ep.ee_state_rpc,0); if(!client.server) goto done;
    memset(state_buffer,0,sizeof(state_buffer));
    d_call(&client,0,0,state_buffer,4,state_buffer,0,0,0);
    memset(state_buffer,0,sizeof(state_buffer)); SMAPGetMACAddress((uint8_t *)state_buffer);
    d_call(&client,1,0,state_buffer,8,state_buffer,4,0,0);
    if(d_add(ep.iop_out_cmd,outgoing_command,0)<0) goto done; tx_handler=1;
    if(d_add(ep.iop_ready_cmd,credit_command,0)<0) goto done; credit_handler=1;
    rpc_id=thread(rpc_thread,16); if(rpc_id<0) goto done; WaitSema(rpc_up);
    if(d_buffers(&desc,&ep)<0 || !ep.ee_buffer || terminating) goto done;
    printf("EENT buffer handshake complete\\n");
    while(!terminating) {
        s=lock(); pending=control_pending; control_pending=0; unlock(s);
        if(pending&1) ready(active?1:0); transmit_one(); receive_one();
        if(++tick>=1000u || (pending&2)) {
            uint32_t state,media; tick=0; smap_get_link_status(&link,&mode);
            state=link?3u:2u; media=media_from_smap(mode);
            if(state!=old_state) { notify(2,state); old_state=state; }
            if(media!=old_media) { notify(3,media); old_media=media; }
        }
        DelayThread(1000);
    }
done:
    active=0; terminating=1; clear_queue();
    if(claimed) { smap_release_game_rx_callback(receive_frame); claimed=0; }
    if(tx_handler) { d_remove(ep.iop_out_cmd); tx_handler=0; }
    if(credit_handler) { d_remove(ep.iop_ready_cmd); credit_handler=0; }
    if(rpc_id>=0) {
        sceSifRemoveRpc(&server,&rpc_queue); sceSifRemoveRpcQueue(&rpc_queue);
        TerminateThread(rpc_id); DeleteThread(rpc_id); rpc_id=-1;
    }
    if(registered) { d_unregister(&desc,&ep); registered=0; }
    printf("EENT stopped; rx-dropped=%u tx-errors=%u\\n",(unsigned)rx_dropped,(unsigned)tx_errors);
    ExitThread();
}
int eent_loaded(void) { return loaded; }
int eent_launch(void)
{
    int r;
    if(loaded) return terminating?-1:0;
    if(resolve()<0) { printf("EENT missing/unsupported ent_devm 1.1\\n"); return -1; }
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
'''
NEW['iop/smap_eenet/src/main.c'] = r'''#include <irx.h>
#include <intrman.h>
#include <loadcore.h>
#include <stdio.h>
#include <sysclib.h>
#include <xmodload.h>
#include "ioplib.h"
#include "adapter.h"
#define VIRTUAL_ID 0x1f01
IRX_ID("smap_eenet",1,0);
static int (*old_loadstart)(char *,int,char *,int *);
static int (*old_start)(int,char *,int,char *,int *);
static int (*old_loadbuf)(void *);
static int (*old_stop)(int,int,char *,int *);
static int (*old_unload)(int);
static int (*old_search)(const char *);
static int (*old_refer)(int,ModuleStatus *);
static int name_is_ent(const char *s) { return s && !strcmp(s,"ent_smap"); }
static int path_is_ent(const char *s)
{ return s && (strstr(s,"ENT_SMAP.IRX") || strstr(s,"ent_smap.irx")); }
static int launch(int *res)
{
    int r=eent_launch();
    if(res) *res=r<0?MODULE_NO_RESIDENT_END:MODULE_REMOVABLE_END;
    return r<0?r:VIRTUAL_ID;
}
static int hook_loadstart(char *path,int n,char *args,int *res)
{
    if(path_is_ent(path)) return launch(res);
    return old_loadstart(path,n,args,res);
}
static int hook_start(int id,char *name,int n,char *args,int *res)
{
    if(id==VIRTUAL_ID) return launch(res);
    return old_start(id,name,n,args,res);
}
static int hook_loadbuf(void *image)
{
    ModuleStatus status; int id=old_loadbuf(image);
    if(id<0) return id;
    memset(&status,0,sizeof(status));
    if(old_refer(id,&status)>=0 && name_is_ent(status.name)) {
        if(old_unload(id)<0) {
            printf("EENT cannot discard unstarted original module id=%d\\n",id); return -1;
        }
        printf("EENT intercepted buffered ENT_SMAP\\n"); return VIRTUAL_ID;
    }
    return id;
}
static int hook_stop(int id,int n,char *args,int *res)
{
    if(id==VIRTUAL_ID) {
        printf("EENT stop rejected: experimental adapter stays resident\\n"); return -1;
    }
    return old_stop(id,n,args,res);
}
static int hook_unload(int id) { return id==VIRTUAL_ID?-1:old_unload(id); }
static int hook_search(const char *name)
{
    if(name_is_ent(name)) return eent_loaded()?VIRTUAL_ID:-202;
    return old_search(name);
}
static int hook_refer(int id,ModuleStatus *status)
{
    if(id==VIRTUAL_ID) {
        if(!status) return -1; memset(status,0,sizeof(*status));
        strcpy(status->name,"ent_smap"); status->version=0x021f; status->id=VIRTUAL_ID; return id;
    }
    return old_refer(id,status);
}
int _start(int argc,char *argv[])
{
    iop_library_t *lib=ioplib_getByName("modload\\0"); (void)argc; (void)argv;
    if(!lib || lib->version<=0x0102 || ioplib_getTableSize(lib)<=22u) return MODULE_NO_RESIDENT_END;
    old_loadstart=ioplib_hookExportEntry(lib,7,hook_loadstart);
    old_start=ioplib_hookExportEntry(lib,8,hook_start);
    old_loadbuf=ioplib_hookExportEntry(lib,10,hook_loadbuf);
    old_refer=ioplib_hookExportEntry(lib,17,hook_refer);
    old_stop=ioplib_hookExportEntry(lib,20,hook_stop);
    old_unload=ioplib_hookExportEntry(lib,21,hook_unload);
    old_search=ioplib_hookExportEntry(lib,22,hook_search);
    ioplib_relinkExports(lib); printf("EENT experimental shim resident\\n"); return MODULE_RESIDENT_END;
}
'''
NEW['iop/smap/include/online_mux.h'] = r'''#ifndef SMAP_ONLINE_MUX_H
#define SMAP_ONLINE_MUX_H
#include <stdint.h>
#define SMAP_TO_HOST 1u
#define SMAP_TO_GAME 2u
static unsigned smap_online_targets(const uint8_t *h,unsigned n,uint32_t host_ip,
    int shared_ip,const uint16_t *ports,unsigned count)
{
    unsigned type,i,bcast=1;
    if(!h || n<14u) return 0;
    for(i=0;i<6u;++i) if(h[i]!=255u) bcast=0;
    type=((unsigned)h[12]<<8)|h[13];
    if(type==0x0806u) return 3u;
    if(type==0x0800u && n>=34u && (h[14]>>4)==4u && (h[14]&15u)>=5u) {
        uint32_t dst=((uint32_t)h[30]<<24)|((uint32_t)h[31]<<16)|((uint32_t)h[32]<<8)|h[33];
        unsigned ihl=(h[14]&15u)*4u;
        int ours=(host_ip && dst==host_ip),all=(dst==0xffffffffu || bcast);
        if((ours || all) && h[23]==17u && n>=14u+ihl+4u && !(h[20]&0x3fu) && !h[21]) {
            unsigned port=((unsigned)h[14u+ihl+2u]<<8)|h[14u+ihl+3u];
            for(i=0;i<count;++i) if(ports[i]==port) return SMAP_TO_HOST;
        }
        if(all) return 3u; if(ours) return shared_ip?3u:SMAP_TO_HOST; return SMAP_TO_GAME;
    }
    return bcast?3u:SMAP_TO_GAME;
}
#endif
'''
OWNERSHIP = r'''int smap_register_game_rx_callback(int (*cb)(uint16_t,const uint8_t *,uint16_t))
{
    int old; CpuSuspendIntr(&old);
    if(g_game_rx_owner && cb!=g_game_rx_owner) { CpuResumeIntr(old); return -1; }
    g_game_rx_callback=cb; CpuResumeIntr(old); return 0;
}
int smap_claim_game_rx_callback(int (*cb)(uint16_t,const uint8_t *,uint16_t))
{
    int old; if(!cb) return -1; CpuSuspendIntr(&old);
    if(g_game_rx_callback && g_game_rx_callback!=cb) { CpuResumeIntr(old); return -1; }
    g_game_rx_owner=cb; g_game_rx_callback=cb; CpuResumeIntr(old); return 0;
}
int smap_release_game_rx_callback(int (*cb)(uint16_t,const uint8_t *,uint16_t))
{
    int old; CpuSuspendIntr(&old);
    if(!cb || g_game_rx_owner!=cb) { CpuResumeIntr(old); return -1; }
    g_game_rx_callback=0; g_game_rx_owner=0; CpuResumeIntr(old); return 0;
}
int smap_reserve_host_udp_port(uint16_t port)
{
    unsigned i; int old; if(!port) return -1; CpuSuspendIntr(&old);
    for(i=0;i<g_host_udp_count;++i) if(g_host_udp_ports[i]==port) { CpuResumeIntr(old); return 0; }
    if(g_host_udp_count==4u) { CpuResumeIntr(old); return -1; }
    g_host_udp_ports[g_host_udp_count++]=port; CpuResumeIntr(old); return 0;
}
'''
DISPATCH = r'''static void dispatch_rx_mux(uint16_t length,uint16_t hdr_len)
{
    unsigned targets=smap_online_targets(g_hdr_buf,hdr_len,g_host_ip,
        g_game_rx_owner!=0,g_host_udp_ports,g_host_udp_count);
    if((targets&SMAP_TO_HOST) && g_rx_callback) g_rx_callback(length,g_hdr_buf,hdr_len);
    if((targets&SMAP_TO_GAME) && g_game_rx_callback) g_game_rx_callback(length,g_hdr_buf,hdr_len);
}
'''
HEADER = '''
int smap_claim_game_rx_callback(int (*cb)(uint16_t,const uint8_t *,uint16_t));
int smap_release_game_rx_callback(int (*cb)(uint16_t,const uint8_t *,uint16_t));
int smap_reserve_host_udp_port(uint16_t port);
#define I_smap_claim_game_rx_callback DECLARE_IMPORT(13, smap_claim_game_rx_callback)
#define I_smap_release_game_rx_callback DECLARE_IMPORT(14, smap_release_game_rx_callback)
#define I_smap_reserve_host_udp_port DECLARE_IMPORT(15, smap_reserve_host_udp_port)
'''

def once(s,a,b,p):
    if s.count(a)!=1: raise ValueError(p+': expected one anchor '+repr(a[:70]))
    return s.replace(a,b,1)

def plan(root):
    out={}
    def read(p): return (root/p).read_text()
    p='iop/smap/src/xfer.c'; s=read(p)
    s=once(s,'#include "main.h"','#include "main.h"\n#include "online_mux.h"',p)
    s=once(s,'static uint32_t g_host_ip = 0;',
        'static uint32_t g_host_ip = 0;\nstatic int (*g_game_rx_owner)(uint16_t,const uint8_t *,uint16_t)=0;\nstatic uint16_t g_host_udp_ports[4];\nstatic unsigned g_host_udp_count;',p)
    a=s.index('int smap_register_game_rx_callback('); b=s.index('\nvoid smap_set_host_ip(',a)
    s=s[:a]+OWNERSHIP+s[b:]
    a=s.index('static void dispatch_rx_mux('); b=s.index('\nint HandleRxIntr(',a)
    out[p]=s[:a]+DISPATCH+s[b:]
    p='iop/smap/include/smap.h'; s=read(p); pos=s.rfind('#endif')
    if pos<0: raise ValueError(p+': no endif')
    out[p]=s[:pos]+HEADER+s[pos:]
    p='iop/smap/src/exports.tab'
    out[p]=once(read(p),'END_EXPORT_TABLE','    DECLARE_EXPORT(smap_claim_game_rx_callback)\n    DECLARE_EXPORT(smap_release_game_rx_callback)\n    DECLARE_EXPORT(smap_reserve_host_udp_port)\nEND_EXPORT_TABLE',p)
    p='iop/smap_inet/src/main.c'
    out[p]=once(read(p),'    g_started = 1;\n    g_dev_ops.flags |= (sceInetDevF_Up | sceInetDevF_Running);\n    smap_register_game_rx_callback(smap_inet_rx_cb);',
        '    if (smap_register_game_rx_callback(smap_inet_rx_cb) < 0)\n        return -1;\n    g_started = 1;\n    g_dev_ops.flags |= (sceInetDevF_Up | sceInetDevF_Running);',p)
    p='iop/udpfs/src/udprdma.c'
    out[p]=once(read(p),'    /* Bind UDP socket */','    if (smap_reserve_host_udp_port(s->port) < 0)\n        return NULL;\n\n    /* Bind UDP socket */',p)
    p='iop/udpfs/src/imports.lst'
    out[p]=once(read(p),'smap_IMPORTS_end','I_smap_reserve_host_udp_port\nsmap_IMPORTS_end',p)
    p='Makefile'; result=[]; hits=0
    for line in read(p).splitlines(True):
        result.append(line)
        if line.startswith('\t') and 'iop/smap_inet' in line:
            result.append(line.replace('smap_inet','smap_eenet')); hits+=1
    if hits!=3: raise ValueError('Makefile: expected 3 build anchors')
    out[p]=''.join(result)
    p='ee/loader/config/bsd-udpfs-net.toml'; s=read(p)
    blocks=list(re.finditer(r'(?ms)^\[\[fake\]\]\s*\n(?:(?!^\[\[).)*',s))
    selected=[m for m in blocks if re.search(r'^file\s*=\s*"ENT_SMAP\.IRX"\s*$',m.group(),re.M)]
    if len(selected)!=1: raise ValueError(p+': expected one ENT_SMAP fake block')
    m=selected[0]; s=s[:m.start()]+s[m.end():]
    s=re.sub(r'^# - ENT_SMAP\.IRX.*$','# - ENT_SMAP is intercepted by experimental smap_eenet.irx',s,flags=re.M)
    out[p]=s+'\n[[module]]\nfile = "smap_eenet.irx"\nenv = ["EE"]\n'
    for p,text in NEW.items():
        if (root/p).exists(): raise ValueError('New candidate path already exists: '+p)
        out[p]=text
    return out

if __name__=='__main__':
    if sys.argv[1:] not in (['--check'],['--apply']):
        raise SystemExit('usage: python3 pc/eent_candidate.py --check|--apply')
    root=Path(__file__).resolve().parents[1]
    changes=plan(root)
    print('\n'.join(sorted(changes)))
    print(str(len(changes))+' source/config files staged; prototype is not hardware-validated.')
    if sys.argv[1]=='--apply':
        for p,text in changes.items():
            dest=root/p; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_text(text)
        print('Applied experimental EENET build candidate.')
