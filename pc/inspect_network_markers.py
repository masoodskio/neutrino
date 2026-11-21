"""Read-only marker scan; matches are clues, not proof of executed drivers."""
import argparse
import hashlib
import json

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('image')
a = p.parse_args()
markers = [b'INET_SMAP_driver', b'ent_smap', b'SMAP_driver', b'SMAP.IRX', b'ENT_SMAP.IRX', b'netdev', b'ent_devm', b'SCE/SMAP']
hits = {m.decode(): [] for m in markers}
counts = {m.decode(): 0 for m in markers}
digest = hashlib.sha256()
overlap = max(map(len, markers)) - 1
tail = b''
position = 0
with open(a.image, 'rb') as f:
    while True:
        block = f.read(1024 * 1024)
        if not block:
            break
        digest.update(block)
        data = tail + block
        base = position - len(tail)
        for marker in markers:
            start = 0
            while True:
                i = data.find(marker, start)
                if i < 0:
                    break
                if base + i + len(marker) > position:
                    key = marker.decode()
                    counts[key] += 1
                    if len(hits[key]) < 16:
                        hits[key].append(hex(base + i))
                start = i + 1
        position += len(block)
        tail = data[-overlap:]
print(json.dumps({'bytes': position, 'sha256': digest.hexdigest(), 'markers': {k: {'count': counts[k], 'first_offsets': v} for k, v in hits.items()}, 'warning': 'Raw uncompressed ISO only. Strings may be unused or belong to the setup utility. Absence does not rule out compressed or renamed modules. This does not establish compatibility.'}, indent=2))
