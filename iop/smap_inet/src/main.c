#include <intrman.h>
#include <irx.h>
#include <loadcore.h>
#include <smapregs.h>
#include <stdio.h>
#include <sysclib.h>
#include <thbase.h>
#include <thevent.h>
#include <xmodload.h>
#include "elf.h"
#include "ioplib.h"
#include "mprintf.h"
#include "netdev.h"
#include "smap.h"
#define MODNAME "smap_inet_shim"
IRX_ID(MODNAME, 1, 0);
#define SHIM_FAKE_MOD_ID 0x1F00
#define SHIM_MOD_NAME "INET_SMAP_driver"
#define SHIM_MOD_VERSION 0x0219

typedef int (*fn_RegisterNetDevice)(sceInetDevOps_t *ops);
typedef int (*fn_UnregisterNetDevice)(sceInetDevOps_t *ops);
typedef void (*fn_PktEnQ)(sceInetPktQ_t *que, sceInetPkt_t *pkt);
typedef sceInetPkt_t *(*fn_PktDeQ)(sceInetPktQ_t *que);
typedef sceInetPkt_t *(*fn_AllocPkt)(sceInetDevOps_t *ops, int siz);
typedef void (*fn_FreePkt)(sceInetDevOps_t *ops, sceInetPkt_t *pkt);
static fn_RegisterNetDevice g_netdev_register = NULL;
static fn_UnregisterNetDevice g_netdev_unregister = NULL;
static fn_PktEnQ g_netdev_pkt_enq = NULL;
static fn_PktDeQ g_netdev_pkt_deq = NULL;
static fn_AllocPkt g_netdev_alloc_pkt = NULL;
static fn_FreePkt g_netdev_free_pkt = NULL;
static int (*org_LoadStartModule)(char *, int, char *, int *);
static int (*org_StartModule)(int, char *, int, char *, int *);
static int (*org_LoadModuleBuffer)(void *);
static int (*org_StopModule)(int, int, char *, int *);
static int (*org_UnloadModule)(int);
static int (*org_SearchModuleByName)(const char *);
static int (*org_ReferModuleStatus)(int, ModuleStatus *);
static sceInetDevOps_t g_dev_ops;
static int g_attached = 0, g_started = 0, g_thread_pri = 16;
static u32 g_rx_packets, g_tx_packets, g_rx_bytes, g_tx_bytes, g_rx_dropped;
static int is_smap_path(const char *path)
{
    if (path == NULL) return 0;
    if (strstr(path, "ENT_SMAP") || strstr(path, "ent_smap")) return 0;
    return strstr(path, "SMAP.IRX") != NULL || strstr(path, "smap.irx") != NULL;
}
static int is_smap_modname(const char *name)
{
    if (name == NULL) return 0;
    return strstr(name, "INET_SMAP_driver") != NULL || strstr(name, "SMAP_driver") != NULL;
}
static uint32_t eth_crc32(const uint8_t *addr)
{
    uint32_t crc = 0xFFFFFFFF;
    int i, j;
    for (i = 0; i < 6; i++) {
        uint8_t byte = addr[i];
        for (j = 0; j < 8; j++) {
            uint32_t b = (byte ^ crc) & 1;
            crc >>= 1;
            if (b) crc ^= 0xEDB88320;
            byte >>= 1;
        }
    }
    return crc;
}
static int smap_inet_rx_cb(uint16_t len, const uint8_t *hdr, uint16_t hdr_len)
{
    sceInetPkt_t *pkt;
    uint32_t read_len;
    (void)hdr; (void)hdr_len;
    if (!g_started || g_netdev_alloc_pkt == NULL || g_netdev_pkt_enq == NULL) return -1;
    if (len == 0 || len > 1536) return -1;
    read_len = (len + 3) & ~3;
    pkt = g_netdev_alloc_pkt(&g_dev_ops, read_len);
    if (pkt == NULL) { g_rx_dropped++; return -1; }
    smap_fifo_read(0, pkt->rp, read_len);
    pkt->wp = pkt->rp + len;
    g_rx_packets++; g_rx_bytes += len;
    g_netdev_pkt_enq(&g_dev_ops.rcvq, pkt);
    if (g_dev_ops.evfid >= 0) SetEventFlag(g_dev_ops.evfid, sceInetDevEFP_Recv);
    return 0;
}
static int smap_inet_start(void *priv, int flags)
{
    (void)priv; (void)flags;
    g_started = 1;
    g_dev_ops.flags |= (sceInetDevF_Up | sceInetDevF_Running);
    smap_register_game_rx_callback(smap_inet_rx_cb);
    if (g_dev_ops.evfid >= 0) SetEventFlag(g_dev_ops.evfid, sceInetDevEFP_StartDone);
    return 0;
}
static int smap_inet_stop(void *priv, int flags)
{
    (void)priv; (void)flags;
    g_started = 0;
    g_dev_ops.flags &= ~(sceInetDevF_Up | sceInetDevF_Running);
    smap_register_game_rx_callback(NULL);
    if (g_netdev_pkt_deq != NULL && g_netdev_free_pkt != NULL) {
        sceInetPkt_t *pkt;
        while ((pkt = g_netdev_pkt_deq(&g_dev_ops.sndq)) != NULL)
            g_netdev_free_pkt(&g_dev_ops, pkt);
    }
    return 0;
}
static int smap_inet_xmit(void *priv, int flags)
{
    sceInetPkt_t *pkt;
    (void)priv; (void)flags;
    if (!g_started || g_netdev_pkt_deq == NULL || g_netdev_free_pkt == NULL) return 0;
    while ((pkt = g_netdev_pkt_deq(&g_dev_ops.sndq)) != NULL) {
        int pkt_len = (int)(pkt->wp - pkt->rp);
        if (pkt_len > 0 && pkt_len <= 1536) {
            smap_transmit(pkt->rp, (uint16_t)pkt_len, NULL, 0);
            g_tx_packets++; g_tx_bytes += (u32)pkt_len;
        }
        g_netdev_free_pkt(&g_dev_ops, pkt);
    }
    return 0;
}
static int smap_inet_control(void *priv, int code, void *ptr, int len)
{
    uint8_t link_status = 0, link_mode = 0;
    (void)priv;
    switch (code) {
    case sceInetNDCC_GET_THPRI:
        if (len < 4 || ptr == NULL) return -1;
        *(int *)ptr = g_thread_pri; return 0;
    case sceInetNDCC_SET_THPRI:
        if (len < 4 || ptr == NULL) return -1;
        g_thread_pri = *(int *)ptr; return 0;
    case sceInetNDCC_GET_IF_TYPE:
        if (len < 4 || ptr == NULL) return -1;
        *(int *)ptr = sceInetNDIFT_ETHERNET; return 0;
    case sceInetNDCC_GET_LINK_STATUS:
        if (len < 4 || ptr == NULL) return -1;
        smap_get_link_status(&link_status, NULL);
        *(int *)ptr = link_status ? 1 : 0; return 0;
    case sceInetNDCC_GET_NEGO_MODE:
    case sceInetNDCC_GET_NEGO_STATUS:
        if (len < 4 || ptr == NULL) return -1;
        smap_get_link_status(NULL, &link_mode);
        *(int *)ptr = (int)link_mode | sceInetNDNEGO_AUTO; return 0;
    case sceInetNDCC_SET_NEGO_MODE:
        /* Neutrino owns shared PHY negotiation. */
        return 0;
    case sceInetNDCC_SET_MULTICAST_LIST: {
        uint32_t hash[4] = {0, 0, 0, 0};
        const uint8_t *addrs = (const uint8_t *)ptr;
        int count = len / 6, i;
        for (i = 0; i < count; i++) {
            uint32_t crc = eth_crc32(&addrs[i * 6]);
            uint32_t idx = (crc >> 26) & 0x3F;
            hash[idx >> 4] |= (1u << (idx & 0x0F));
        }
        smap_set_multicast_hash(hash);
        smap_set_rx_mode(SMAP_E3_RX_MCAST | SMAP_E3_RX_BCAST);
        return 0;
    }
    case sceInetNDCC_GET_RX_PACKETS:
        if (len < 4 || ptr == NULL) return -1;
        *(u32 *)ptr = g_rx_packets; return 0;
    case sceInetNDCC_GET_TX_PACKETS:
        if (len < 4 || ptr == NULL) return -1;
        *(u32 *)ptr = g_tx_packets; return 0;
    case sceInetNDCC_GET_RX_BYTES:
        if (len < 4 || ptr == NULL) return -1;
        *(u32 *)ptr = g_rx_bytes; return 0;
    case sceInetNDCC_GET_TX_BYTES:
        if (len < 4 || ptr == NULL) return -1;
        *(u32 *)ptr = g_tx_bytes; return 0;
    case sceInetNDCC_GET_RX_DROPPED:
        if (len < 4 || ptr == NULL) return -1;
        *(u32 *)ptr = g_rx_dropped; return 0;
    default:
        if (ptr != NULL && len >= 4 && ((code & 0x01000000) == 0)) *(u32 *)ptr = 0;
        return 0;
    }
}
static int smap_inet_attach(void)
{
    iop_library_t *lib_netdev;
    if (g_attached) return 0;
    lib_netdev = ioplib_getByName("netdev\0\0");
    if (lib_netdev == NULL || ioplib_getTableSize(lib_netdev) < 14) return -200;
    g_netdev_register = (fn_RegisterNetDevice)lib_netdev->exports[4];
    g_netdev_unregister = (fn_UnregisterNetDevice)lib_netdev->exports[5];
    g_netdev_pkt_enq = (fn_PktEnQ)lib_netdev->exports[8];
    g_netdev_pkt_deq = (fn_PktDeQ)lib_netdev->exports[9];
    g_netdev_alloc_pkt = (fn_AllocPkt)lib_netdev->exports[12];
    g_netdev_free_pkt = (fn_FreePkt)lib_netdev->exports[13];
    memset(&g_dev_ops, 0, sizeof(g_dev_ops));
    g_dev_ops.module_name = SHIM_MOD_NAME;
    g_dev_ops.vendor_name = "SCE";
    g_dev_ops.device_name = "Ethernet (Network Adaptor)";
    g_dev_ops.bus_type = sceInetBus_NIC;
    g_dev_ops.prot_ver = sceInetDevProtVer;
    g_dev_ops.impl_ver = 0;
    g_dev_ops.priv = &g_dev_ops;
    g_dev_ops.flags = sceInetDevF_Broadcast | sceInetDevF_ARP | sceInetDevF_NIC | sceInetDevF_Multicast;
    g_dev_ops.evfid = -1;
    g_dev_ops.start = smap_inet_start;
    g_dev_ops.stop = smap_inet_stop;
    g_dev_ops.xmit = smap_inet_xmit;
    g_dev_ops.control = smap_inet_control;
    g_dev_ops.mtu = 1500;
    SMAPGetMACAddress(g_dev_ops.hw_addr);
    if (g_netdev_register(&g_dev_ops) < 0) return -1;
    g_attached = 1;
    return 0;
}
static void smap_inet_detach(void)
{
    if (!g_attached) return;
    smap_inet_stop(&g_dev_ops, 0);
    if (g_netdev_unregister != NULL) g_netdev_unregister(&g_dev_ops);
    g_attached = 0;
    g_netdev_register = NULL; g_netdev_unregister = NULL;
    g_netdev_pkt_enq = NULL; g_netdev_pkt_deq = NULL;
    g_netdev_alloc_pkt = NULL; g_netdev_free_pkt = NULL;
}
static int Hook_LoadStartModule(char *modpath, int arg_len, char *args, int *modres)
{
    if (is_smap_path(modpath)) {
        int r = smap_inet_attach();
        if (r < 0) {
            if (modres != NULL) *modres = MODULE_NO_RESIDENT_END;
            return r;
        }
        if (modres != NULL) *modres = MODULE_REMOVABLE_END;
        return SHIM_FAKE_MOD_ID;
    }
    return org_LoadStartModule(modpath, arg_len, args, modres);
}
static int Hook_StartModule(int id, char *modname, int arg_len, char *args, int *modres)
{
    if (id == SHIM_FAKE_MOD_ID) {
        int r = smap_inet_attach();
        if (r < 0) {
            if (modres != NULL) *modres = MODULE_NO_RESIDENT_END;
            return r;
        }
        if (modres != NULL) *modres = MODULE_REMOVABLE_END;
        return SHIM_FAKE_MOD_ID;
    }
    return org_StartModule(id, modname, arg_len, args, modres);
}
static int Hook_LoadModuleBuffer(void *ptr)
{
    elf_header_t *eh = (elf_header_t *)ptr;
    elf_pheader_t *eph = (elf_pheader_t *)((uint8_t *)ptr + eh->phoff);
    const char *modname = (const char *)ptr + eph->offset + 0x1a;
    if (is_smap_modname(modname)) return SHIM_FAKE_MOD_ID;
    return org_LoadModuleBuffer(ptr);
}
static int Hook_StopModule(int id, int arg_len, char *args, int *modres)
{
    if (id == SHIM_FAKE_MOD_ID) {
        smap_inet_detach();
        if (modres != NULL) *modres = MODULE_NO_RESIDENT_END;
        return SHIM_FAKE_MOD_ID;
    }
    return org_StopModule(id, arg_len, args, modres);
}
static int Hook_UnloadModule(int id)
{
    if (id == SHIM_FAKE_MOD_ID) { smap_inet_detach(); return SHIM_FAKE_MOD_ID; }
    return org_UnloadModule(id);
}
static int Hook_SearchModuleByName(const char *modname)
{
    if (is_smap_modname(modname)) return g_attached ? SHIM_FAKE_MOD_ID : -202;
    return org_SearchModuleByName(modname);
}
static int Hook_ReferModuleStatus(int id, ModuleStatus *status)
{
    if (id == SHIM_FAKE_MOD_ID && g_attached && status != NULL) {
        memset(status, 0, sizeof(ModuleStatus));
        strcpy(status->name, SHIM_MOD_NAME);
        status->version = SHIM_MOD_VERSION; status->id = SHIM_FAKE_MOD_ID;
        return id;
    }
    return org_ReferModuleStatus(id, status);
}
int _start(int argc, char *argv[])
{
    iop_library_t *lib_modload;
    (void)argc; (void)argv;
    lib_modload = ioplib_getByName("modload\0");
    if (lib_modload == NULL) return MODULE_NO_RESIDENT_END;
    org_LoadStartModule = ioplib_hookExportEntry(lib_modload, 7, Hook_LoadStartModule);
    org_StartModule = ioplib_hookExportEntry(lib_modload, 8, Hook_StartModule);
    org_LoadModuleBuffer = ioplib_hookExportEntry(lib_modload, 10, Hook_LoadModuleBuffer);
    if (lib_modload->version > 0x102) {
        org_ReferModuleStatus = ioplib_hookExportEntry(lib_modload, 17, Hook_ReferModuleStatus);
        org_StopModule = ioplib_hookExportEntry(lib_modload, 20, Hook_StopModule);
        org_UnloadModule = ioplib_hookExportEntry(lib_modload, 21, Hook_UnloadModule);
        org_SearchModuleByName = ioplib_hookExportEntry(lib_modload, 22, Hook_SearchModuleByName);
    }
    ioplib_relinkExports(lib_modload);
    return MODULE_RESIDENT_END;
}
