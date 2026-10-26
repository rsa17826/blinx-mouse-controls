#!/usr/bin/env python3
"""stride_scan.py <snapshot.bin> <base_hex> <value> [max_stride]
Finds 10 equally spaced bytes equal to <value> in a pmemsave snapshot.
<base_hex> is the physical address the snapshot starts at (the scan
range base you gave interactive_scan.py, or 0 for a full dump).
<value> is decimal, or 0x-prefixed hex. Fill all 10 slots with the same
item before taking the snapshot."""

import sys

import numpy as np

path = sys.argv[1]
base = int(sys.argv[2], 16)
value = int(sys.argv[3], 0)
max_stride = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x100
COUNT = 10

data = np.fromfile(path, dtype=np.uint8)
n = len(data)
mask = data == value
idx = np.flatnonzero(mask)
print(f"{len(idx)} bytes equal {value} (0x{value:02x}) in {n} bytes")

for stride in range(1, max_stride + 1):
  c = idx[idx + (COUNT - 1) * stride < n]
  for k in range(1, COUNT):
    c = c[mask[c + k * stride]]
    if len(c) == 0:
      break


  for start in c:
    start = int(start)
    phys = base + start
    print(f"stride 0x{stride:x}: phys 0x{phys:08x}  (virt 0xf0000000+phys = 0x{0xF0000000 + phys:08x})")
    print(f"    before: {data[max(0, start - 16) : start].tobytes().hex(' ')}")
    print(f"    run:    {data[start : start + (COUNT - 1) * stride + 1].tobytes().hex(' ')}")

