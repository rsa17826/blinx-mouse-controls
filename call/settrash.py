#!/usr/bin/env python
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from fastmem import FastMemWriter

mem = FastMemWriter()
try:
  thing = bytes.fromhex(sys.argv[1])
  mem.write(0x009E374D, bytes([0xA]))
  for addr in range(1, 12, 0x1):
    mem.write(0x009E374D + addr, thing)


finally:
  mem.close()
