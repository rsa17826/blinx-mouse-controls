#!/usr/bin/env python3
"""TEST ONLY: continuously copy player heading (+0x8c) into player+0x34.

Usage:
    python3 mirror_heading.py <ram_host_base_hex>

If aim/facing becomes correct while this runs, the game reads +0x34.
Ctrl-C to stop.
"""
import struct
import subprocess
import sys
import time

PHYS_OFFSET = 0xAF000
PLAYER = 0x4EAA20
HEADING = PLAYER + 0x8C
LATCH = PLAYER + 0x34
RATE_HZ = 240


def find_xemu_pid():
  out = subprocess.check_output(["pgrep", "-fa", "^xemu"]).decode()
  return int(out.split()[0])


ram_base = int(sys.argv[1], 16)
pid = find_xemu_pid()
fd = open(f"/proc/{pid}/mem", "r+b", buffering=0)


def host(addr):
  return ram_base + addr + PHYS_OFFSET


interval = 1.0 / RATE_HZ
try:
  while True:
    fd.seek(host(HEADING))
    raw = fd.read(4)
    if len(raw) != 4:
      raise RuntimeError("short read of heading")
    fd.seek(host(LATCH))
    fd.write(raw)
    time.sleep(interval)
except KeyboardInterrupt:
  print("\nStopped.")
finally:
  fd.close()
