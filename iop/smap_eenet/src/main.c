#include <stdint.h>
#include <irx.h>
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
/* EENT_CONFIG_TRACE_V1: observe configuration before adapter activation. */
static int config_trace_installed;
static int (*original_config_apply)(void *);
static int (*original_config_add)(void *,void *);
static int (*original_config_remove)(void *);
/* Read-only candidate strings, not a parser for the NETCNF schema. */
#define CFG_RAM_FIRST ((uintptr_t)0x1000u)
#define CFG_RAM_END ((uintptr_t)0x200000u)
#define CFG_ROOT_WORDS 256u
#define CFG_CHILD_WORDS 64u
#define CFG_STRING_LINES 40u
#define CFG_STRING_BYTES 127u
static int cfg_range(uintptr_t p,unsigned n)
{
    return p>=CFG_RAM_FIRST && p<CFG_RAM_END && n<=CFG_RAM_END-p;
}
static int cfg_word(uintptr_t p,uint32_t *value)
{
    if(!cfg_range(p,4u)) return 0;
    memcpy(value,(const void *)p,4u);
    return 1;
}
static int cfg_printable(uintptr_t p,char text[255])
{
    unsigned n,out=0;
    if(!cfg_range(p,1u)) return 0;
    for(n=0;n<CFG_STRING_BYTES;++n) {
        unsigned char c;
        if(!cfg_range(p+n,1u)) return 0;
        c=*(const unsigned char *)(p+n);
        if(!c) {
            if(!n) return 0;
            text[out]=0;
            return 1;
        }
        if(c<0x20u || c>0x7eu) return 0;
        if(c=='"' || c=='\\') text[out++]='\\';
        text[out++]=(char)c;
    }
    return 0;
}
static void cfg_emit(uintptr_t p,unsigned root_off,int indirect,unsigned child_off,
    uintptr_t seen[CFG_STRING_LINES],unsigned *lines)
{
    char text[255]; unsigned i;
    if(*lines>=CFG_STRING_LINES) return;
    for(i=0;i<*lines;++i) if(seen[i]==p) return;
    if(!cfg_printable(p,text)) return;
    seen[*lines]=p;
    ++*lines;
    if(indirect)
        printf("EENT-CFG s[+%03x->+%03x]=\"%s\"\n",root_off,child_off,text);
    else
        printf("EENT-CFG s[+%03x]=\"%s\"\n",root_off,text);
}
static void dump_config_strings(void *env)
{
    uintptr_t base=(uintptr_t)env,seen[CFG_STRING_LINES];
    unsigned i,j,lines=0;
    if(!cfg_range(base,4u)) return;
    for(i=0;i<CFG_ROOT_WORDS && lines<CFG_STRING_LINES;++i) {
        uint32_t pointer;
        uintptr_t child;
        if(!cfg_word(base+4u*i,&pointer)) break;
        child=(uintptr_t)pointer;
        if(!cfg_range(child,1u)) continue;
        cfg_emit(child,4u*i,0,0,seen,&lines);
        for(j=0;j<CFG_CHILD_WORDS && lines<CFG_STRING_LINES;++j) {
            uint32_t nested;
            if(!cfg_word(child+4u*j,&nested)) break;
            cfg_emit((uintptr_t)nested,4u*i,1,4u*j,seen,&lines);
        }
    }
}

static int trace_config_apply(void *env)
{
    int r;
    printf("EENT-CFG apply begin env=%p\n",env);
    dump_config_strings(env);
    r=original_config_apply(env);
    eent_force_status();
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

static int hook_loadstart(char *path,int n,char *args,int *res)
{
    int r;
    if(path_is_ent(path)) return launch(res);
    r=old_loadstart(path,n,args,res);
    if(r>=0) install_config_trace();
    return r;
}
static int hook_start(int id,char *name,int n,char *args,int *res)
{
    int r;
    if(id==VIRTUAL_ID) return launch(res);
    r=old_start(id,name,n,args,res);
    if(r>=0) install_config_trace();
    return r;
}
static int hook_loadbuf(void *image)
{
    ModuleStatus status; int id=old_loadbuf(image);
    if(id<0) return id;
    memset(&status,0,sizeof(status));
    if(old_refer(id,&status)>=0 && name_is_ent(status.name)) {
        if(old_unload(id)<0) {
            printf("EENT cannot discard unstarted original module id=%d\n",id); return -1;
        }
        printf("EENT intercepted buffered ENT_SMAP\n"); return VIRTUAL_ID;
    }
    return id;
}
static int hook_stop(int id,int n,char *args,int *res)
{
    if(id==VIRTUAL_ID) {
        printf("EENT stop rejected: experimental adapter stays resident\n"); return -1;
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
    iop_library_t *lib=ioplib_getByName("modload\0"); (void)argc; (void)argv;
    if(!lib || lib->version<=0x0102 || ioplib_getTableSize(lib)<=22u) return MODULE_NO_RESIDENT_END;
    old_loadstart=ioplib_hookExportEntry(lib,7,hook_loadstart);
    old_start=ioplib_hookExportEntry(lib,8,hook_start);
    old_loadbuf=ioplib_hookExportEntry(lib,10,hook_loadbuf);
    old_refer=ioplib_hookExportEntry(lib,17,hook_refer);
    old_stop=ioplib_hookExportEntry(lib,20,hook_stop);
    old_unload=ioplib_hookExportEntry(lib,21,hook_unload);
    old_search=ioplib_hookExportEntry(lib,22,hook_search);
    ioplib_relinkExports(lib); printf("EENT experimental shim resident\n"); return MODULE_RESIDENT_END;
}
