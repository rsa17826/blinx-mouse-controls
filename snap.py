#!/usr/bin/env python3
"""physmap.py <dump.bin> <virt_addr_hex> [len]
Reads len bytes (default 64) at a known virtual address via the stub,
then finds them in a pmemsave dump taken at the same moment.
Use the IL struct: python3 physmap.py dump.bin 509680"""

import sys

import numpy as np

import gdb_rsp

dump = np.fromfile(sys.argv[1], dtype=np.uint8).tobytes()
virt = int(sys.argv[2], 16)
length = int(sys.argv[3]) if len(sys.argv) > 3 else 64

sock = gdb_rsp.connect()
try:
  live = gdb_rsp.read_memory(sock, virt, length)

finally:
  gdb_rsp.cmd_continue(sock)

start = 0
hits = []
while True:
  i = dump.find(live, start)
  if i == -1:
    break

  hits.append(i)
  start = i + 1

print(f"virt 0x{virt:08x} -> physical hits: {[hex(h) for h in hits]}")
