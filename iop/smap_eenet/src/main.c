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
            printf("smap_eenet: cannot discard unstarted original module id=%d\n",id); return -1;
        }
        return VIRTUAL_ID;
    }
    return id;
}
static int hook_stop(int id,int n,char *args,int *res)
{
    if(id==VIRTUAL_ID) {
        printf("smap_eenet: adapter stop/unload is not supported\n"); return -1;
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
        if(!status) return -1;
        memset(status,0,sizeof(*status));
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
    ioplib_relinkExports(lib); return MODULE_RESIDENT_END;
}
