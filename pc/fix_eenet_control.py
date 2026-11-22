#!/usr/bin/env python3
"""Accept the native payload-free EENET start/stop control requests."""
from pathlib import Path
import sys

OLD = """    if(bytes<4 || bytes>(int)sizeof(rpc_buffer)) return buf;
    memcpy(&value,buf,4);"""
NEW = """    /* EENT_CTL_ZERO_LENGTH_V1: native function 1 has no request payload. */
    if(bytes<0 || bytes>(int)sizeof(rpc_buffer) || (bytes>0 && !buf)) return buf;
    value=0;
    if(bytes==0) {
        if(fn!=1 && fn!=2) return buf;
        if(!buf) buf=rpc_buffer;
    } else {
        if(bytes<4) return buf;
        memcpy(&value,buf,4);
    }"""
BANNER_ANCHOR = "    uint8_t link,mode; int pending,s; (void)arg;"
BANNER = r'    printf("EENT control ABI v2: payload-free start/stop\n");'


def transform(source):
    if "EENT_CTL_ZERO_LENGTH_V1" in source:
        raise ValueError("Payload-free control correction already applied")
    if source.count(OLD)!=1 or source.count(BANNER_ANCHOR)!=1:
        raise ValueError("Expected exactly one control validation and worker banner anchor")
    source=source.replace(OLD,NEW,1)
    return source.replace(BANNER_ANCHOR,BANNER_ANCHOR+"\n"+BANNER,1)


if __name__=="__main__":
    if sys.argv[1:] not in ([],["--check"]):
        raise SystemExit("usage: python3 pc/fix_eenet_control.py [--check]")
    path=Path(__file__).resolve().parents[1]/"iop/smap_eenet/src/adapter.c"
    result=transform(path.read_text())
    if not sys.argv[1:]:
        path.write_text(result)
    print("Payload-free EENET control anchors validated"+(" (check only)" if sys.argv[1:] else "; correction applied"))
