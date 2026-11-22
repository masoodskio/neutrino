#ifndef SMAP_ONLINE_MUX_H
#define SMAP_ONLINE_MUX_H
#include <stdint.h>
#define SMAP_TO_HOST 1u
#define SMAP_TO_GAME 2u
/* Keep reserved storage UDP traffic on ministack while sharing other frames. */
static unsigned smap_online_targets(const uint8_t *h,unsigned n,uint32_t host_ip,
    int shared_ip,const uint16_t *ports,unsigned count)
{
    unsigned type,i,bcast=1;
    if(!h || n<14u) return 0;
    for(i=0;i<6u;++i) if(h[i]!=255u) bcast=0;
    type=((unsigned)h[12]<<8)|h[13];
    if(type==0x0806u) return 3u;
    if(type==0x0800u && n>=34u && (h[14]>>4)==4u && (h[14]&15u)>=5u) {
        uint32_t dst=((uint32_t)h[30]<<24)|((uint32_t)h[31]<<16)|((uint32_t)h[32]<<8)|h[33];
        unsigned ihl=(h[14]&15u)*4u;
        int ours=(host_ip && dst==host_ip),all=(dst==0xffffffffu || bcast);
        if((ours || all) && h[23]==17u && n>=14u+ihl+4u && !(h[20]&0x3fu) && !h[21]) {
            unsigned port=((unsigned)h[14u+ihl+2u]<<8)|h[14u+ihl+3u];
            for(i=0;i<count;++i) if(ports[i]==port) return SMAP_TO_HOST;
        }
        if(all) return 3u;
        if(ours) return shared_ip?3u:SMAP_TO_HOST;
        return SMAP_TO_GAME;
    }
    return bcast?3u:SMAP_TO_GAME;
}
#endif
