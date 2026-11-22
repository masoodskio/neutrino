#ifndef SMAP_H
#define SMAP_H

#include <stdint.h>
#include <irx.h>

/**
 * Read bytes from the current RX frame (frame-relative offset).
 * Must be called from within an RX callback registered with smap.
 * Uses DMA for large transfers (>= 64 bytes), PIO otherwise.
 */
void smap_fifo_read(uint16_t offset, void *dst, uint32_t bytes);

/**
 * Register the primary (ministack) callback for received Ethernet frames.
 * SMAP will pre-read n_bytes from the start of each frame into a buffer and pass it to cb.
 * @param cb       Callback invoked for each received frame (from SMAP IST thread)
 * @param n_bytes  Number of header bytes to pre-read (max 64); 0 = no pre-read
 */
int smap_register_rx_callback(int (*cb)(uint16_t len, const uint8_t *hdr, uint16_t hdr_len), uint16_t n_bytes);

/**
 * Read the hardware MAC address into a 6-byte buffer.
 */
int SMAPGetMACAddress(uint8_t *buffer);

/**
 * Transmit a packet (header + optional separate data payload).
 */
int smap_transmit(void *header, uint16_t headersize, const void *data, uint16_t datasize);

/**
 * Register (or unregister with NULL) a secondary game shim RX callback.
 * When active, SMAP demultiplexes incoming frames between ministack (matching host_ip)
 * and the game shim (other IPv4/EtherTypes), fanning out ARP and L2 broadcasts to both.
 */
int smap_register_game_rx_callback(int (*cb)(uint16_t len, const uint8_t *hdr, uint16_t hdr_len));

/**
 * Set ministack's IPv4 address (host byte order: (a<<24)|(b<<16)|(c<<8)|d) for RX demuxing.
 */
void smap_set_host_ip(uint32_t ip);

/**
 * Query current Ethernet link status and negotiated LinkMode without touching the PHY.
 */
void smap_get_link_status(uint8_t *link_status, uint8_t *link_mode);

/**
 * Program the 4 EMAC3 multicast group hash registers safely.
 */
void smap_set_multicast_hash(const uint32_t hash[4]);

/**
 * Update EMAC3 RX mode flags (promiscuous/multicast/broadcast) without disturbing core bits.
 */
void smap_set_rx_mode(uint32_t rx_mode_flags);

/* Import table — slot numbers match exports.tab */
#define smap_IMPORTS_start DECLARE_IMPORT_TABLE(smap, 1, 0)
#define smap_IMPORTS_end   END_IMPORT_TABLE

#define I_SMAPGetMACAddress              DECLARE_IMPORT(4, SMAPGetMACAddress)
#define I_smap_transmit                  DECLARE_IMPORT(5, smap_transmit)
#define I_smap_register_rx_callback      DECLARE_IMPORT(6, smap_register_rx_callback)
#define I_smap_fifo_read                 DECLARE_IMPORT(7, smap_fifo_read)
#define I_smap_register_game_rx_callback DECLARE_IMPORT(8, smap_register_game_rx_callback)
#define I_smap_set_host_ip               DECLARE_IMPORT(9, smap_set_host_ip)
#define I_smap_get_link_status           DECLARE_IMPORT(10, smap_get_link_status)
#define I_smap_set_multicast_hash        DECLARE_IMPORT(11, smap_set_multicast_hash)
#define I_smap_set_rx_mode               DECLARE_IMPORT(12, smap_set_rx_mode)

#endif
