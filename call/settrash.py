#!/usr/bin/env python
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from fastmem import FastMemWriter

mem = FastMemWriter()
try:
  thing = bytes.fromhex(sys.argv[1])
  mem.write(0xF0A9474D, bytes([0xA]))
  for addr in range(0xF0A9474E, 0xF0A94757 + 0x1, 0x1):
    mem.write(addr, thing)

finally:
  mem.close()
