/* Small diagnostic wrapper; no netdev export mutation. */
#include <intrman.h>
#include <irx.h>
#include <loadcore.h>
#include <stdio.h>
#include <xmodload.h>
static void *diag_hook(iop_library_t *, unsigned int, void *);
#define ioplib_hookExportEntry diag_hook
#include "main.c"
#undef ioplib_hookExportEntry
extern void *ioplib_hookExportEntry(iop_library_t *, unsigned int, void *);

static int (*diag_load_original)(void *);
static int (*diag_start_original)(int, char *, int, char *, int *);
static int (*diag_control_original)(void *, int, void *, int);
static unsigned int diag_control_count;

static void diag_memory(unsigned int *total, unsigned int *largest)
{
    iop_library_t *lib = ioplib_getByName("sysmem\0\0");
    *total = *largest = 0;
    if (lib != NULL && ioplib_getTableSize(lib) > 8) {
        unsigned int (*get_total)(void) = (unsigned int (*)(void))lib->exports[8];
        unsigned int (*get_largest)(void) = (unsigned int (*)(void))lib->exports[7];
        if (get_total != NULL && get_largest != NULL) {
            *total = get_total();
            *largest = get_largest();
        }
    }
}

static int diag_control(void *priv, int code, void *ptr, int len)
{
    int result = diag_control_original(priv, code, ptr, len);
    /* Limit synchronous output and do not dereference unknown control buffers. */
    if (diag_control_count++ < 32)
        printf("DIAG ctl=%08x len=%d rv=%d\n", (unsigned int)code, len, result);
    return result;
}

static int diag_load(void *ptr)
{
    unsigned int total_before, max_before, total_after, max_after;
    int result;
    diag_memory(&total_before, &max_before);
    result = diag_load_original(ptr);
    if (result < 0) {
        char name[48];
        unsigned int i;
        /* Same IRX-name location used by the existing buffer interception. */
        elf_header_t *eh = (elf_header_t *)ptr;
        elf_pheader_t *ph = (elf_pheader_t *)((unsigned char *)ptr + eh->phoff);
        const char *src = (const char *)ptr + ph->offset + 0x1a;
        for (i = 0; i < sizeof(name) - 1 && src[i] >= 32 && src[i] <= 126; i++)
            name[i] = src[i];
        name[i] = 0;
        diag_memory(&total_after, &max_after);
        printf("DIAG load fail name=%s rv=%d\n", name, result);
        printf("DIAG memory before total=%u max=%u after total=%u max=%u\n", total_before, max_before, total_after, max_after);
    }
    return result;
}

static int diag_start_module(int id, char *name, int n, char *args, int *res)
{
    int result = diag_start_original(id, name, n, args, res);
    if (id == SHIM_FAKE_MOD_ID && g_attached && g_dev_ops.control != diag_control) {
        diag_control_original = g_dev_ops.control;
        g_dev_ops.control = diag_control;
        diag_control_count = 0;
        printf("DIAG attached if=%.9s bus=%u flags=%x evfid=%d\n", g_dev_ops.interface, g_dev_ops.bus_type, g_dev_ops.flags, g_dev_ops.evfid);
    }
    return result;
}

static void *diag_hook(iop_library_t *lib, unsigned int slot, void *replacement)
{
    if (slot == 10) {
        diag_load_original = (int (*)(void *))replacement;
        replacement = (void *)diag_load;
    } else if (slot == 8) {
        diag_start_original = (int (*)(int, char *, int, char *, int *))replacement;
        replacement = (void *)diag_start_module;
    }
    return ioplib_hookExportEntry(lib, slot, replacement);
}
