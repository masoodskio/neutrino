/* Diagnostics wrapper around the unchanged shim implementation. */
#include <intrman.h>
#include <irx.h>
#include <loadcore.h>
#include <stdio.h>
#include <sysclib.h>
#include <xmodload.h>
#include "netdev.h"

static void *trace_hook_export(iop_library_t *, unsigned int, void *);
static int trace_register(sceInetDevOps_t *);
static int trace_control(void *, int, void *, int);
static int trace_start(void *, int);
static int trace_stop(void *, int);

/* Redirect registration lookup and hook installation locally, not globally. */
static iop_library_t *trace_lookup(const char *);
#define ioplib_getByName trace_lookup
#define ioplib_hookExportEntry trace_hook_export
#include "main.c"
#undef ioplib_getByName
#undef ioplib_hookExportEntry

extern iop_library_t *ioplib_getByName(const char *);
extern void *ioplib_hookExportEntry(iop_library_t *, unsigned int, void *);

static int (*real_register)(sceInetDevOps_t *);
static int (*real_control)(void *, int, void *, int);
static int (*real_start)(void *, int);
static int (*real_stop)(void *, int);
static int (*shim_load_start)(char *, int, char *, int *);
static int (*shim_start_module)(int, char *, int, char *, int *);
static int (*shim_load_buffer)(void *);
static int (*shim_search)(const char *);
static int (*shim_status)(int, ModuleStatus *);

/* Only the registration export is temporarily redirected during lookup.
 * Restore it before calling the real register function. No import relinking.
 */
static iop_library_t *registration_library;
static iop_library_t *trace_lookup(const char *name)
{
    iop_library_t *lib = ioplib_getByName(name);
    if (name[0] == 'n' && name[1] == 'e' && name[2] == 't' &&
        name[3] == 'd' && name[4] == 'e' && name[5] == 'v' && name[6] == 0) {
        printf("TRACE netdev lookup found=%d version=0x%x\n", lib != NULL, lib ? lib->version : 0);
        if (lib != NULL && ioplib_getTableSize(lib) >= 14) {
            int oldstate;
            CpuSuspendIntr(&oldstate);
            registration_library = lib;
            real_register = (int (*)(sceInetDevOps_t *))lib->exports[4];
            lib->exports[4] = (void *)trace_register;
            CpuResumeIntr(oldstate);
        }
    }
    return lib;
}

static int trace_control(void *priv, int code, void *ptr, int len)
{
    int result;
    unsigned int value = 0;
    printf("TRACE control enter code=0x%08x len=%d ptr=%p\n", (unsigned int)code, len, ptr);
    result = real_control(priv, code, ptr, len);
    if (ptr != NULL && len >= 4)
        memcpy(&value, ptr, 4);
    printf("TRACE control exit code=0x%08x rv=%d firstword=0x%08x valid=%d\n", (unsigned int)code, result, value, ptr != NULL && len >= 4);
    return result;
}

static int trace_start(void *priv, int flags)
{
    int result;
    printf("TRACE device start flags=0x%x\n", flags);
    result = real_start(priv, flags);
    printf("TRACE device start rv=%d evfid=%d\n", result, g_dev_ops.evfid);
    return result;
}

static int trace_stop(void *priv, int flags)
{
    int result;
    printf("TRACE device stop flags=0x%x\n", flags);
    result = real_stop(priv, flags);
    printf("TRACE device stop rv=%d\n", result);
    return result;
}

static int trace_register(sceInetDevOps_t *ops)
{
    int result, oldstate;
    CpuSuspendIntr(&oldstate);
    registration_library->exports[4] = (void *)real_register;
    CpuResumeIntr(oldstate);
    real_control = ops->control;
    real_start = ops->start;
    real_stop = ops->stop;
    ops->control = trace_control;
    ops->start = trace_start;
    ops->stop = trace_stop;
    printf("TRACE register before bus=%u prot=%u impl=%u flags=0x%x evfid=%d\n", ops->bus_type, ops->prot_ver, ops->impl_ver, ops->flags, ops->evfid);
    result = real_register(ops);
    printf("TRACE register after rv=%d interface=%.9s vendor=%s device=%s\n", result, ops->interface, ops->vendor_name ? ops->vendor_name : "(null)", ops->device_name ? ops->device_name : "(null)");
    printf("TRACE identity flags=0x%x mtu=%d evfid=%d\n", ops->flags, ops->mtu, ops->evfid);
    return result;
}

static int trace_load_start(char *path, int n, char *args, int *res)
{
    int result;
    printf("TRACE LoadStart path=%s arglen=%d\n", path ? path : "(null)", n);
    result = shim_load_start(path, n, args, res);
    printf("TRACE LoadStart rv=%d\n", result);
    return result;
}

static int trace_start_module(int id, char *name, int n, char *args, int *res)
{
    int result;
    printf("TRACE StartModule id=%d arglen=%d\n", id, n);
    result = shim_start_module(id, name, n, args, res);
    printf("TRACE StartModule rv=%d\n", result);
    return result;
}

static int trace_load_buffer(void *ptr)
{
    int result;
    printf("TRACE LoadBuffer ptr=%p\n", ptr);
    result = shim_load_buffer(ptr);
    printf("TRACE LoadBuffer rv=%d\n", result);
    return result;
}

static int trace_search(const char *name)
{
    int result = shim_search(name);
    printf("TRACE SearchModule name=%s rv=%d\n", name ? name : "(null)", result);
    return result;
}

static int trace_status(int id, ModuleStatus *status)
{
    int result = shim_status(id, status);
    printf("TRACE ReferModule id=%d rv=%d\n", id, result);
    if (id == SHIM_FAKE_MOD_ID && status != NULL && g_attached)
        printf("TRACE shim status version=0x%x name=%.32s\n", status->version, status->name);
    return result;
}

static void *trace_hook_export(iop_library_t *lib, unsigned int slot, void *replacement)
{
    switch (slot) {
        case 7: shim_load_start = (int (*)(char *, int, char *, int *))replacement; replacement = (void *)trace_load_start; break;
        case 8: shim_start_module = (int (*)(int, char *, int, char *, int *))replacement; replacement = (void *)trace_start_module; break;
        case 10: shim_load_buffer = (int (*)(void *))replacement; replacement = (void *)trace_load_buffer; break;
        case 17: shim_status = (int (*)(int, ModuleStatus *))replacement; replacement = (void *)trace_status; break;
        case 22: shim_search = (int (*)(const char *))replacement; replacement = (void *)trace_search; break;
        default: break;
    }
    return ioplib_hookExportEntry(lib, slot, replacement);
}
