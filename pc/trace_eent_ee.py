#!/usr/bin/env python3
"""Guarded Battlefront II EE activation telemetry; requires paired EE core and shim.
No forced start, network setting changes, or on-disc game ELF changes.
"""
from pathlib import Path
import sys

HEADER = r'''#ifndef EENT_EE_TRACE_H
#define EENT_EE_TRACE_H
#include <stdint.h>
#define EENT_TRACE_MAGIC 0x544e4545u
#define EENT_TRACE_TAG 0x21240001u
struct eent_trace_slot {
    uint32_t entered,exited,result,fn,bytes,server,phase,state;
    uint32_t reserved[8];
};
struct eent_trace_data {
    uint32_t magic,version,tag,armed,guard_address,guard_actual,guard_expected;
    uint32_t reserved[9];
    struct eent_trace_slot up,rpc;
    uint32_t spare[16];
};
typedef char eent_trace_size[sizeof(struct eent_trace_data)==256?1:-1];
#endif
'''

EE = r'''/* Battlefront II SLUS_212.40 diagnostic only; no forced activation. */
#include <kernel.h>
#include <sifrpc.h>
#include "util.h"
#include "eecore_config.h"
#include "eent_ee_trace.h"
#define EENT_JAL(p) (0x0c000000u|(((uint32_t)(p)>>2)&0x03ffffffu))
#define EENT_J(p) (0x08000000u|(((uint32_t)(p)>>2)&0x03ffffffu))
static struct eent_trace_data eent_trace __attribute__((section(".eent_trace"),aligned(64),used));
static uint32_t eent_up_trampoline[4] __attribute__((aligned(16)));
#ifndef EENT_NATIVE_UP
#define EENT_NATIVE_UP ((int (*)(const char *))(void *)eent_up_trampoline)
#endif
#ifndef EENT_NATIVE_RPC
#define EENT_NATIVE_RPC ((int (*)(SifRpcClientData_t *,int,int,void *,int,void *,int,SifRpcEndFunc_t,void *))0x005ee0d8)
#endif
static void eent_flush(void *p,unsigned n)
{
    SyncDCache(p,(void *)((char *)p+n));
}
static void eent_enter(struct eent_trace_slot *p,uint32_t fn,int bytes,uint32_t server)
{
    int enabled=DIntr();
    ++p->entered; p->fn=fn; p->bytes=(uint32_t)bytes; p->server=server;
    p->phase=_lw(0x006029d8); p->state=_lw(0x006fcc94);
    eent_flush(p,sizeof(*p));
    if(enabled) EIntr();
}
static void eent_exit(struct eent_trace_slot *p,int result)
{
    int enabled=DIntr();
    ++p->exited; p->result=(uint32_t)result;
    eent_flush(p,sizeof(*p));
    if(enabled) EIntr();
}
static int eent_up(const char *name)
{
    int result;
    eent_enter(&eent_trace.up,(uint32_t)name,0,0);
    result=EENT_NATIVE_UP(name);
    eent_exit(&eent_trace.up,result);
    return result;
}
static int eent_rpc(SifRpcClientData_t *cd,int fn,int mode,void *send,int bytes,
    void *recv,int recv_bytes,SifRpcEndFunc_t end,void *arg)
{
    uint32_t context=_lw(0x00739a80);
    int result,trace=cd && context && (uint32_t)cd==context+9800u;
    if(trace) eent_enter(&eent_trace.rpc,(uint32_t)fn,bytes,(uint32_t)cd->server);
    result=EENT_NATIVE_RPC(cd,fn,mode,send,bytes,recv,recv_bytes,end,arg);
    if(trace) eent_exit(&eent_trace.rpc,result);
    return result;
}
static int eent_guard(uint32_t address,uint32_t expected)
{
    uint32_t actual=_lw(address);
    if(actual==expected) return 1;
    eent_trace.guard_address=address; eent_trace.guard_actual=actual;
    eent_trace.guard_expected=expected;
    eent_flush(&eent_trace,64);
    return 0;
}
void eent_install_trace(const char *path)
{
    static const uint32_t up[8]={0x27bdfff0,0x0000282d,0xffbf0000,0x0c146352,
        0x24060001,0xdfbf0000,0x03e00008,0x27bd0010};
    static const uint32_t reg[8]={0x27bdffc0,0x3c080074,0xffb20020,0x24020001,
        0xffb00000,0x3c030052,0x3c060052,0x3c070052};
    static const uint32_t calls[5]={0x0051a6c0,0x0051a8a4,0x0051a9d8,0x0051aa20,0x0051ad1c};
    volatile uint32_t *words=(volatile uint32_t *)&eent_trace;
    unsigned i;
    if(!path || _strcmp(eec.GameID,"SLUS_212.40") ||
        _strcmp(path,"cdrom0:\\SWBFRNT2.ELF;1")) return;
    for(i=0;i<sizeof(eent_trace)/4u;++i) words[i]=0;
    eent_trace.magic=EENT_TRACE_MAGIC; eent_trace.version=1;
    eent_trace.tag=EENT_TRACE_TAG; eent_flush(&eent_trace,64);
    for(i=0;i<8u;++i) if(!eent_guard(0x00518f68+4u*i,up[i])) return;
    for(i=0;i<8u;++i) if(!eent_guard(0x00519bf8+4u*i,reg[i])) return;
    for(i=0;i<5u;++i) if(!eent_guard(calls[i],EENT_JAL(0x004df770))) return;
    if(!eent_guard(0x004df7f0,EENT_JAL(0x005ee0d8))) return;
    eent_up_trampoline[0]=up[0]; eent_up_trampoline[1]=up[1];
    eent_up_trampoline[2]=EENT_J(0x00518f70); eent_up_trampoline[3]=0;
    _sw(EENT_J(eent_up),0x00518f68); _sw(0,0x00518f6c);
    _sw(EENT_JAL(eent_rpc),0x004df7f0);
    eent_trace.armed=1; eent_flush(&eent_trace,sizeof(eent_trace));
    /* apply_patches caller flushes D/I caches before CleanExecPS2. */
}
'''

IOP = r'''/* Persistent storage also remains valid after a timed-out asynchronous read. */
#include "eent_ee_trace.h"
static SifRpcReceiveData_t eent_ee_rd __attribute__((aligned(16)));
static struct eent_trace_data eent_ee_copy __attribute__((aligned(64)));
static unsigned eent_ee_clock,eent_ee_wait,eent_ee_samples;
static uint32_t eent_ee_address=0x00093f00u;
static int eent_ee_busy,eent_ee_disabled,eent_ee_found;
static void eent_ee_poll(void)
{
    int result;
    if(eent_ee_disabled) return;
    if(eent_ee_busy) {
        if(*(void *volatile *)&eent_ee_rd.hdr.pkt_addr) {
            if(++eent_ee_wait>=2000u) {
                printf("EENT-EE read timeout; disabled, buffer retained\n");
                eent_ee_disabled=1;
            }
            return;
        }
        eent_ee_busy=0;
        if(eent_ee_copy.magic!=EENT_TRACE_MAGIC || eent_ee_copy.version!=1u ||
            eent_ee_copy.tag!=EENT_TRACE_TAG) {
            if(!eent_ee_found && eent_ee_address==0x00093f00u) {
                eent_ee_address=0x000a5f00u; eent_ee_clock=999u;
            } else {
                printf("EENT-EE trace missing/incompatible; paired ee_core.elf required\n");
                eent_ee_disabled=1;
            }
            return;
        }
        eent_ee_found=1;
        if(!eent_ee_copy.armed) {
            printf("EENT-EE guard refused address=%08x got=%08x expected=%08x\n",
                (unsigned)eent_ee_copy.guard_address,(unsigned)eent_ee_copy.guard_actual,
                (unsigned)eent_ee_copy.guard_expected);
            eent_ee_disabled=1; return;
        }
        ++eent_ee_samples;
        printf("EENT-EE sample=%u up entered=%u exited=%u result=%d nameptr=%08x phase=%08x state=%08x\n",
            eent_ee_samples,(unsigned)eent_ee_copy.up.entered,(unsigned)eent_ee_copy.up.exited,
            (int)eent_ee_copy.up.result,(unsigned)eent_ee_copy.up.fn,
            (unsigned)eent_ee_copy.up.phase,(unsigned)eent_ee_copy.up.state);
        printf("EENT-EE rpc entered=%u exited=%u fn=%u bytes=%d server=%08x result=%d\n",
            (unsigned)eent_ee_copy.rpc.entered,(unsigned)eent_ee_copy.rpc.exited,
            (unsigned)eent_ee_copy.rpc.fn,(int)eent_ee_copy.rpc.bytes,
            (unsigned)eent_ee_copy.rpc.server,(int)eent_ee_copy.rpc.result);
        printf("EENT-EE local server=%08x fn=%d client=%08x queue=%08x active=%d thread=%d\n",
            (unsigned)(uintptr_t)&server,server.rpc_number,(unsigned)(uintptr_t)server.client,
            (unsigned)(uintptr_t)rpc_queue.start,rpc_queue.active,rpc_queue.thread_id);
        if(eent_ee_samples>=16u) { eent_ee_disabled=1; return; }
    }
    if(++eent_ee_clock<1000u) return;
    eent_ee_clock=0; eent_ee_wait=0;
    result=sceSifGetOtherData(&eent_ee_rd,(void *)(uintptr_t)eent_ee_address,
        &eent_ee_copy,sizeof(eent_ee_copy),SIF_RPC_M_NOWAIT);
    if(result<0) {
        printf("EENT-EE read submit failed result=%d; disabled\n",result);
        eent_ee_disabled=1; return;
    }
    eent_ee_busy=1;
}
'''

LINK = r'''
    /* EENT_EE_TRACE_V1: reserve the final cache lines of the protected core. */
    .eent_trace (ORIGIN(MAIN_REGION) + LENGTH(MAIN_REGION) - 256) (NOLOAD) : {
        KEEP(*(.eent_trace))
    } >MAIN_REGION :text
    ASSERT(_end_bss <= ADDR(.eent_trace), "EENET trace overlaps EE core")
    ASSERT(SIZEOF(.eent_trace) == 256, "EENET trace layout mismatch")
'''

def replace_once(source,old,new,path):
    if source.count(old)!=1:
        raise ValueError(path+": expected one anchor "+repr(old[:80]))
    return source.replace(old,new,1)


def plan(root):
    changes={}
    def edit(path,old,new):
        source=changes.get(path)
        if source is None: source=(root/path).read_text()
        changes[path]=replace_once(source,old,new,path)
    edit("ee/ee_core/Makefile","EE_OBJS = main.o","EE_OBJS = eent_trace.o main.o")
    edit("ee/ee_core/src/patches.c","void apply_patches(const char *path)\n{",
        "extern void eent_install_trace(const char *path);\n\nvoid apply_patches(const char *path)\n{")
    edit("ee/ee_core/src/patches.c","    const patchlist_t *p;",
        "    const patchlist_t *p;\n    eent_install_trace(path);")
    edit("ee/ee_core/linkfile","_stack_end = _stack + _stack_size;",
        "_stack_end = _stack + _stack_size;\n"+LINK)
    edit("ee/ee_core/linkfile","_heap_size = -1; /* automatically from _end to _stack */",
        "_heap_size = ADDR(.eent_trace) - _end; /* exclude diagnostic buffer */")
    edit("iop/smap_eenet/src/imports.lst","sifcmd_IMPORTS_end",
        "I_sceSifGetOtherData\nsifcmd_IMPORTS_end")
    edit("iop/smap_eenet/src/adapter.c","static void worker(void *arg)",
        IOP+"\nstatic void worker(void *arg)")
    edit("iop/smap_eenet/src/adapter.c","        DelayThread(1000);",
        "        eent_ee_poll();\n        DelayThread(1000);")
    for path,source in {
        "ee/ee_core/src/eent_trace.c":EE,
        "ee/ee_core/include/eent_ee_trace.h":HEADER,
        "iop/smap_eenet/src/eent_ee_trace.h":HEADER,
    }.items():
        if (root/path).exists(): raise ValueError("Trace path already exists: "+path)
        changes[path]=source
    return changes



def verify_build(root):
    import hashlib
    import struct
    core_path=root/"ee/loader/modules/ee_core.elf"
    shim_path=root/"ee/loader/modules/smap_eenet.irx"
    core=core_path.read_bytes()
    shim=shim_path.read_bytes()
    if len(core)<52 or core[:6]!=b"\x7fELF\x01\x01" or struct.unpack_from("<H",core,18)[0]!=8:
        raise ValueError("Expected a little-endian ELF32 MIPS EE core")
    offset=struct.unpack_from("<I",core,32)[0]
    stride,count,names_index=struct.unpack_from("<HHH",core,46)
    if stride<40 or names_index>=count or offset+stride*count>len(core):
        raise ValueError("Invalid EE section table")
    sections=[struct.unpack_from("<10I",core,offset+i*stride) for i in range(count)]
    names_header=sections[names_index]
    start,size=names_header[4:6]
    if start+size>len(core): raise ValueError("Invalid EE section names")
    names=core[start:start+size]
    found=[h for h in sections if names[h[0]:].split(b"\0",1)[0]==b".eent_trace"]
    if len(found)!=1 or found[0][1]!=8 or found[0][3] not in (0x93f00,0xa5f00) or found[0][5]!=256:
        raise ValueError("Missing/invalid protected EE telemetry section")
    if b"EENT-EE read timeout; disabled, buffer retained" not in shim:
        raise ValueError("Paired shim lacks the EE telemetry reader")
    for path,data in ((core_path,core),(shim_path,shim)):
        print(str(path.relative_to(root))+" sha256="+hashlib.sha256(data).hexdigest())


if __name__=="__main__":
    if sys.argv[1:]==["--verify-build"]:
        verify_build(Path(__file__).resolve().parents[1])
        raise SystemExit(0)
    if sys.argv[1:] not in ([],["--check"]):
        raise SystemExit("usage: python3 pc/trace_eent_ee.py [--check|--verify-build]")
    changes=plan(Path(__file__).resolve().parents[1])
    if not sys.argv[1:]:
        for path,source in changes.items():
            target=Path(__file__).resolve().parents[1]/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(source)
    print(str(len(changes))+" EE/IOP trace files validated"+(" (check only)" if sys.argv[1:] else "; applied"))
