"""Capture Neutrino UDP TTY broadcasts; does not modify PS2 or network settings."""
import argparse
import datetime
import socket

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', default='neutrino-tty.log')
p.add_argument('--source', default='192.168.137.10')
a = p.parse_args()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.bind(('0.0.0.0', 18194))
except OSError as e:
    raise SystemExit(f'Cannot listen on UDP 18194: {e}')
print(f'Listening on UDP 18194; source filter {a.source}; appending to {a.output}', flush=True)
print('Leave this running before booting NHDDL. Ctrl+C stops capture.', flush=True)
with open(a.output, 'a', encoding='utf-8', buffering=1) as log:
    try:
        while True:
            data, peer = s.recvfrom(65535)
            if a.source and peer[0] != a.source:
                continue
            stamp = datetime.datetime.now().isoformat(timespec='milliseconds')
            line = f'[{stamp} {peer[0]}:{peer[1]}] ' + data.decode('utf-8', errors='replace')
            if not line.endswith('\n'):
                line += '\n'
            print(line, end='', flush=True)
            log.write(line)
    except KeyboardInterrupt:
        pass
s.close()
