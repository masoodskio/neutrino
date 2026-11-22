#!/usr/bin/env python3
# Experimental: resolve the control-server RPC API after the game loads its stack.
from pathlib import Path
import re
import sys

BINDING = r'''
/* EENT_RUNTIME_RPC_V1: use one runtime sifcmd export table for the server. */
static __typeof__(&sceSifSetRpcQueue) runtime_set_queue;
static __typeof__(&sceSifRegisterRpc) runtime_register;
static __typeof__(&sceSifRpcLoop) runtime_loop;
static __typeof__(&sceSifRemoveRpc) runtime_remove;
static __typeof__(&sceSifRemoveRpcQueue) runtime_remove_queue;
static unsigned runtime_import_target(uintptr_t stub)
{
    uint32_t word=*(const volatile uint32_t *)stub;
    if((word&0xfc000000u)==0x08000000u)
        return (unsigned)(((stub+4u)&0xf0000000u)|((word&0x03ffffffu)<<2));
    return (unsigned)stub;
}
static int bind_runtime_rpc(void)
{
    iop_library_t *lib=ioplib_getByName("sifcmd\0");
    if(!lib || ioplib_getTableSize(lib)<=25u || !lib->exports[17] ||
       !lib->exports[19] || !lib->exports[22] || !lib->exports[24] || !lib->exports[25]) {
        printf("EENT-RPC runtime sifcmd exports unavailable; refusing mixed server API\n");
        return -1;
    }
    runtime_register=(__typeof__(runtime_register))lib->exports[17];
    runtime_set_queue=(__typeof__(runtime_set_queue))lib->exports[19];
    runtime_loop=(__typeof__(runtime_loop))lib->exports[22];
    runtime_remove=(__typeof__(runtime_remove))lib->exports[24];
    runtime_remove_queue=(__typeof__(runtime_remove_queue))lib->exports[25];
    printf("EENT-RPC runtime binding v1 lib=%08x version=%04x\n",
        (unsigned)(uintptr_t)lib,(unsigned)lib->version);
    printf("EENT-RPC set linked=%08x runtime=%08x register linked=%08x runtime=%08x\n",
        runtime_import_target((uintptr_t)&sceSifSetRpcQueue),(unsigned)(uintptr_t)runtime_set_queue,
        runtime_import_target((uintptr_t)&sceSifRegisterRpc),(unsigned)(uintptr_t)runtime_register);
    printf("EENT-RPC loop linked=%08x runtime=%08x\n",
        runtime_import_target((uintptr_t)&sceSifRpcLoop),(unsigned)(uintptr_t)runtime_loop);
    return 0;
}
'''
CALLS = {
    "sceSifSetRpcQueue": "runtime_set_queue",
    "sceSifRegisterRpc": "runtime_register",
    "sceSifRpcLoop": "runtime_loop",
    "sceSifRemoveRpc": "runtime_remove",
    "sceSifRemoveRpcQueue": "runtime_remove_queue",
}


def transform(s):
    if "EENT_RUNTIME_RPC_V1" in s:
        raise ValueError("Runtime RPC experiment already applied")
    for old, new in CALLS.items():
        s, count = re.subn(r"\b" + old + r"\(", new + "(", s)
        if count != 1:
            raise ValueError("Expected exactly one call to " + old)
    marker = '#include "adapter.h"'
    if s.count(marker) != 1:
        raise ValueError("Expected one adapter header anchor")
    s = s.replace(marker, marker + "\n" + BINDING, 1)
    anchor = "    rx_credit=sema();"
    if s.count(anchor) != 1:
        raise ValueError("Expected one pre-thread launch anchor")
    s = s.replace(anchor, "    if(bind_runtime_rpc()<0) return -1;\n" + anchor, 1)
    anchor = "    runtime_set_queue(&rpc_queue,GetThreadId());"
    if s.count(anchor) != 1:
        raise ValueError("Expected one RPC queue setup anchor")
    s = s.replace(anchor, r'''    printf("EENT-RPC server setup begin id=%08x thread=%d\n",
        (unsigned)ep.iop_control_rpc,GetThreadId());
''' + anchor, 1)
    anchor = "    SignalSema(rpc_up);"
    if s.count(anchor) != 1:
        raise ValueError("Expected one RPC-server ready anchor")
    s = s.replace(anchor, r'''    printf("EENT-RPC server registered id=%08x; entering runtime loop\n",
        (unsigned)ep.iop_control_rpc);
''' + anchor, 1)
    return s


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("usage: python3 pc/runtime_eent_rpc.py [--check]")
    p = Path(__file__).resolve().parents[1] / "iop/smap_eenet/src/adapter.c"
    result = transform(p.read_text())
    if not sys.argv[1:]:
        p.write_text(result)
    print("Runtime EENET RPC anchors validated" + (" (check only)" if sys.argv[1:] else "; experiment applied"))
