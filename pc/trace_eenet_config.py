#!/usr/bin/env python3
"""Trace the game's EENETCTL configuration exports without changing results."""
from pathlib import Path
import sys

TRACE = r"""
/* EENT_CONFIG_TRACE_V1: observe configuration before adapter activation. */
static int config_trace_installed;
static int (*original_config_apply)(void *);
static int (*original_config_add)(void *,void *);
static int (*original_config_remove)(void *);
static int trace_config_apply(void *env)
{
    int r;
    printf("EENT-CFG apply begin env=%p\n",env);
    r=original_config_apply(env);
    printf("EENT-CFG apply end result=%d\n",r);
    return r;
}
static int trace_config_add(void *name,void *value)
{
    int r;
    printf("EENT-CFG add begin name=%p value=%p\n",name,value);
    r=original_config_add(name,value);
    printf("EENT-CFG add end result=%d\n",r);
    return r;
}
static int trace_config_remove(void *name)
{
    int r;
    printf("EENT-CFG remove begin name=%p\n",name);
    r=original_config_remove(name);
    printf("EENT-CFG remove end result=%d\n",r);
    return r;
}
static void install_config_trace(void)
{
    iop_library_t *lib;
    if(config_trace_installed) return;
    lib=ioplib_getByName("eenetctl");
    if(!lib) return;
    if(lib->version!=0x0101 || ioplib_getTableSize(lib)<9u ||
       !lib->exports[4] || !lib->exports[7] || !lib->exports[8]) {
        printf("EENT-CFG unsupported eenetctl exports; leaving them untouched\n");
        return;
    }
    original_config_apply=(void *)ioplib_hookExportEntry(lib,4,trace_config_apply);
    original_config_add=(void *)ioplib_hookExportEntry(lib,7,trace_config_add);
    original_config_remove=(void *)ioplib_hookExportEntry(lib,8,trace_config_remove);
    config_trace_installed=1;
    ioplib_relinkExports(lib);
    printf("EENT-CFG v1 tracing eenetctl 1.1 exports 4,7,8\n");
}
"""


def replace_one(s,old,new):
    if s.count(old)!=1:
        raise ValueError("Expected one source anchor: " + old)
    return s.replace(old,new,1)


def transform(s):
    if "EENT_CONFIG_TRACE_V1" in s:
        raise ValueError("Configuration trace already applied")
    s=replace_one(s,'static int hook_loadstart(',TRACE+'\nstatic int hook_loadstart(')
    s=replace_one(s,'    if(path_is_ent(path)) return launch(res);',
        '    int r;\n    if(path_is_ent(path)) return launch(res);')
    s=replace_one(s,'    return old_loadstart(path,n,args,res);',
        '    r=old_loadstart(path,n,args,res);\n    if(r>=0) install_config_trace();\n    return r;')
    s=replace_one(s,'    if(id==VIRTUAL_ID) return launch(res);',
        '    int r;\n    if(id==VIRTUAL_ID) return launch(res);')
    s=replace_one(s,'    return old_start(id,name,n,args,res);',
        '    r=old_start(id,name,n,args,res);\n    if(r>=0) install_config_trace();\n    return r;')
    return s


if __name__=="__main__":
    if sys.argv[1:] not in ([],["--check"]):
        raise SystemExit("usage: python3 pc/trace_eenet_config.py [--check]")
    p=Path(__file__).resolve().parents[1]/"iop/smap_eenet/src/main.c"
    result=transform(p.read_text())
    if not sys.argv[1:]:
        p.write_text(result)
    print("EENETCTL configuration trace anchors validated" + (" (check only)" if sys.argv[1:] else "; trace applied"))
