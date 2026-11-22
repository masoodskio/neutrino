/* Diagnostic wrapper; allocation behavior is unchanged. */
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
    if (diag_control_count++ < 32)
        printf("DIAG ctl=%08x len=%d rv=%d\n", (unsigned int)code, len, result);
    return result;
}

static unsigned int diag_u32(const unsigned char *p)
{
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8) |
        ((unsigned int)p[2] << 16) | ((unsigned int)p[3] << 24);
}

static unsigned int diag_u16(const unsigned char *p)
{
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8);
}

static int diag_load(void *ptr)
{
    unsigned int total_before, max_before, total_after, max_after;
    int result;
    diag_memory(&total_before, &max_before);
    result = diag_load_original(ptr);
    diag_memory(&total_after, &max_after);
    printf("DIAG load rv=%d before=%u largest=%u after=%u largest=%u\n",
        result, total_before, max_before, total_after, max_after);
    /* Input has no length argument: inspect only loader-accepted ELF headers
     * or the same header layout already assumed by the interception hook.
     * Segment values describe the image, not an exact allocator request. */
    if (ptr != NULL) {
        const unsigned char *base = (const unsigned char *)ptr;
        if (base[0] == 0x7f && base[1] == 'E' && base[2] == 'L' &&
            base[3] == 'F' && base[4] == 1 && base[5] == 1) {
            unsigned int off = diag_u32(base + 28);
            unsigned int step = diag_u16(base + 42);
            unsigned int count = diag_u16(base + 44);
            unsigned int j;
            if (step >= 32 && step <= 256 && count <= 32 &&
                off >= 52 && off <= 4096 && off + step * count <= 8192) {
                for (j = 0; j < count; j++) {
                    const unsigned char *ph = base + off + step * j;
                    unsigned int type = diag_u32(ph);
                    unsigned int fileoff = diag_u32(ph + 4);
                    if (type == 1) {
                        printf("DIAG segment=%u vaddr=%08x filesz=%u memsz=%u align=%u\n",
                            j, diag_u32(ph + 8), diag_u32(ph + 16),
                            diag_u32(ph + 20), diag_u32(ph + 28));
                    }
                    /* Preserve the existing IRX-name convention, with a
                     * conservative offset limit and bounded text output. */
                    if (j == 0 && fileoff <= 4096) {
                        char name[48];
                        unsigned int i;
                        const unsigned char *src = base + fileoff + 0x1a;
                        for (i = 0; i < sizeof(name) - 1 && src[i] >= 32 && src[i] <= 126; i++)
                            name[i] = src[i];
                        name[i] = 0;
                        printf("DIAG module=%s rv=%d\n", name, result);
                    }
                }
            }
        }
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
