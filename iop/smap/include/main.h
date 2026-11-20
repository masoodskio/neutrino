#ifndef MAIN_H
#define MAIN_H


#include <stdint.h>
#include <thbase.h>
#include "mprintf.h"

#define MODNAME "SMAP"

struct SmapDriverData
{
    volatile u8 *smap_regbase;
    volatile u8 *emac3_regbase;
    unsigned int TxBufferSpaceAvailable;
    unsigned char NumPacketsInTx;
    unsigned char TxBDIndex;
    unsigned char TxDNVBDIndex;
    unsigned char RxBDIndex;
    int Dev9IntrEventFlag;
    int IntrHandlerThreadID;
    unsigned char SmapDriverStarted; // SMAP driver is started.
    unsigned char SmapIsInitialized; // SMAP driver is initialized (software)
    unsigned char NetDevStopFlag;
    unsigned char EnableLinkCheckTimer;
    unsigned char LinkStatus; // Ethernet link is initialized (hardware)
    unsigned char LinkMode;
    iop_sys_clock_t LinkCheckTimer;
    int NetIFID;
};

/* Event flag bits */
#define SMAP_EVENT_START      0x01
#define SMAP_EVENT_INTR       0x04
#define SMAP_EVENT_LINK_CHECK 0x10

/* Function prototypes */
int smap_init(int argc, char *argv[]);
int SMAPGetMACAddress(u8 *buffer);
void smap_get_link_status(uint8_t *link_status, uint8_t *link_mode);
void smap_set_multicast_hash(const uint32_t hash[4]);
void smap_set_rx_mode(uint32_t rx_mode_flags);


#endif
