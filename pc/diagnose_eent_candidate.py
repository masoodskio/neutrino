#!/usr/bin/env python3
# Add bounded EENET diagnostics after eent_candidate.py --apply.
from pathlib import Path
import sys


def instrument(s):
    if "/* EENT_DIAG_V1 */" in s:
        raise ValueError("EENET diagnostics already applied")

    def patch(old, new):
        nonlocal s
        if s.count(old) != 1:
            raise ValueError("Expected one diagnostic anchor: " + repr(old[:90]))
        s = s.replace(old, new, 1)

    patch('static uint32_t rx_dropped,tx_errors;', r'''static uint32_t rx_dropped,tx_errors;
/* EENT_DIAG_V1: never print inside receive/SIF command callbacks. */
static volatile unsigned diag_rx_seen,diag_rx_queued,diag_tx_cmd,diag_credit_cmd;
static volatile int diag_credit_value;
static unsigned diag_ctl_logs,diag_notify_logs,diag_ready_logs,diag_tx_logs,diag_rx_logs;
static void diag_control(const char *stage,int fn,void *buf,int bytes)
{
    uint32_t words[4]={0,0,0,0}; unsigned n;
    if(diag_ctl_logs>=64u) return;
    ++diag_ctl_logs;
    n=bytes>0?(unsigned)bytes:0u;
    if(n>sizeof(words)) n=sizeof(words);
    if(buf && n) memcpy(words,buf,n);
    printf("EENT-D ctl %s fn=%d bytes=%d active=%d words=%08x,%08x,%08x,%08x\n",
        stage,fn,bytes,active,(unsigned)words[0],(unsigned)words[1],
        (unsigned)words[2],(unsigned)words[3]);
}''')
    patch('s=lock(); stamp=epoch;', 's=lock(); ++diag_rx_seen; stamp=epoch;')
    patch('tail=(tail+1u)%2u; ++count;', 'tail=(tail+1u)%2u; ++count; ++diag_rx_queued;')
    patch('(void)packet; (void)arg; tx_pending=1;', '(void)packet; (void)arg; ++diag_tx_cmd; tx_pending=1;')
    patch('struct command *cmd=packet; (void)arg;', 'struct command *cmd=packet; (void)arg;\n    ++diag_credit_cmd; diag_credit_value=cmd->value;')
    patch('    ready_cmd.value=value;\n    d_send(0,ep.ee_ready_cmd,&ready_cmd,sizeof(ready_cmd),0,0,0);', r'''    int r,trace=diag_ready_logs<16u;
    if(trace) { ++diag_ready_logs; printf("EENT-D ready begin cmd=%08x value=%d route=%u\n",
        (unsigned)ep.ee_ready_cmd,value,(unsigned)ready_cmd.route); }
    ready_cmd.value=value;
    r=d_send(0,ep.ee_ready_cmd,&ready_cmd,sizeof(ready_cmd),0,0,0);
    if(trace) printf("EENT-D ready end rv=%d\n",r);''')
    patch('    memset(state_buffer,0,sizeof(state_buffer)); state_buffer[0]=value;', r'''    int trace=diag_notify_logs<64u;
    if(trace) { ++diag_notify_logs; printf("EENT-D notify begin fn=%d value=%08x\n",fn,(unsigned)value); }
    memset(state_buffer,0,sizeof(state_buffer)); state_buffer[0]=value;''')
    patch('    d_call(&client,fn,0,state_buffer,4,state_buffer,4,0,0);', r'''    d_call(&client,fn,0,state_buffer,4,state_buffer,4,0,0);
    if(trace) printf("EENT-D notify end fn=%d reply=%08x\n",fn,(unsigned)state_buffer[0]);''')
    patch('    uint32_t value,hash[4];', '    uint32_t value,hash[4];\n    diag_control("in",fn,buf,bytes);')
    patch('    return buf;\n}\nstatic void rpc_thread', '    diag_control("out",fn,buf,bytes);\n    return buf;\n}\nstatic void rpc_thread')
    patch('    tx_pending=0; n=ee_tx.bytes;', r'''    tx_pending=0; n=ee_tx.bytes;
    if(diag_tx_logs<8u) printf("EENT-D tx begin bytes=%u\n",n);''')
    patch('    if(n<14u || n>FRAME_MAX) { ++tx_errors; ready(active?1:0); return; }', r'''    if(n<14u || n>FRAME_MAX) {
        if(diag_tx_logs<8u) { ++diag_tx_logs; printf("EENT-D tx invalid bytes=%u\n",n); }
        ++tx_errors; ready(active?1:0); return;
    }''')
    patch('    r=smap_transmit(ee_tx.frame,(uint16_t)n,0,0);', r'''    r=smap_transmit(ee_tx.frame,(uint16_t)n,0,0);
    if(diag_tx_logs<8u) { ++diag_tx_logs; printf("EENT-D tx end rv=%d\n",r); }''')
    patch('    unsigned n,padded; int s;', '    unsigned n,padded; int s,r,trace;')
    patch('    d_send(0,ep.ee_in_cmd,&frame_cmd,sizeof(frame_cmd),&to_ee,\n        (void *)(uintptr_t)ep.ee_buffer,(int)padded);', r'''    trace=diag_rx_logs<8u;
    if(trace) { ++diag_rx_logs; printf("EENT-D rx begin bytes=%u dma=%u dest=%08x\n",
        n,padded,(unsigned)ep.ee_buffer); }
    r=d_send(0,ep.ee_in_cmd,&frame_cmd,sizeof(frame_cmd),&to_ee,
        (void *)(uintptr_t)ep.ee_buffer,(int)padded);
    if(trace) printf("EENT-D rx end rv=%d\n",r);''')
    patch('    unsigned tick=0; uint32_t old_state', '    unsigned tick=0,diag_ticks=0; uint32_t old_state')
    patch('    while(!terminating) {', r'''    printf("EENT-D enabled v1 ctl=64 ready=16 notify=64 tx=8 rx=8 status=4\n");
    printf("EENT-D endpoints out=%08x credit=%08x ready=%08x in=%08x iopbuf=%08x eebuf=%08x\n",
        (unsigned)ep.iop_out_cmd,(unsigned)ep.iop_ready_cmd,(unsigned)ep.ee_ready_cmd,
        (unsigned)ep.ee_in_cmd,(unsigned)ep.iop_buffer,(unsigned)ep.ee_buffer);
    while(!terminating) {''')
    patch('            state=link?3u:2u; media=media_from_smap(mode);', r'''            state=link?3u:2u; media=media_from_smap(mode);
            if(diag_ticks<4u) {
                ++diag_ticks;
                printf("EENT-D status active=%d link=%u mode=%02x state=%u media=%08x\n",
                    active,(unsigned)link,(unsigned)mode,(unsigned)state,(unsigned)media);
                printf("EENT-D packets txcmd=%u creditcmd=%u credit=%d rxseen=%u queued=%u dropped=%u txerr=%u\n",
                    diag_tx_cmd,diag_credit_cmd,diag_credit_value,diag_rx_seen,diag_rx_queued,
                    (unsigned)rx_dropped,(unsigned)tx_errors);
            }''')
    return s


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("usage: python3 pc/diagnose_eent_candidate.py [--check]")
    p = Path(__file__).resolve().parents[1] / "iop/smap_eenet/src/adapter.c"
    result = instrument(p.read_text())
    if not sys.argv[1:]:
        p.write_text(result)
    print("EENET diagnostic anchors validated" + (" (check only)" if sys.argv[1:] else "; instrumentation applied"))
