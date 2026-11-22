#!/usr/bin/env python3
"""Normalize source-bundle escaping before generating the experimental shim."""
from pathlib import Path

p = Path(__file__).resolve().with_name("eent_candidate.py")
s = p.read_text()
marker = "NEW['iop/smap_eenet/src/ioplib.c'] = "
a = s.index(marker)
b = s.index("\nNEW[", a)
include = '#include "../../smap_inet/src/ioplib.c"' + chr(10)
s = s[:a] + marker + repr(include) + s[b:]
s = s.replace(chr(92) * 2 + "n", chr(92) + "n")
s = s.replace(chr(92) * 2 + "0", chr(92) + "0")
compile(s, str(p), "exec")
p.write_text(s)
print("Normalized EENET source bundle; Python syntax check passed.")
