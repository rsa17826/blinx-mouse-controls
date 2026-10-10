#!/usr/bin/env python3
"""Dump every player-struct float that is angle-like relative to heading, plus u16 angle candidates."""

import math
import struct
import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory, cmd_continue

PLAYER = 0x4EAA20
SIZE = 0x200
HEADING_OFF = 0x8C
TWO_PI = 2 * math.pi


def angdiff(a, b):
  d = (a - b + math.pi) % TWO_PI - math.pi
  return d


sock = connect()
data = read_memory(sock, PLAYER, SIZE)
cmd_continue(sock)

heading = struct.unpack_from("<f", data, HEADING_OFF)[0]
print(f"heading={heading:.3f}")
for off in range(0, SIZE - 3, 4):
  v = struct.unpack_from("<f", data, off)[0]
  if not (-10.0 < v < 10.0) or v == 0.0 or v != v:
    continue

  for label, ref in (("h", heading), ("h-pi", heading - math.pi), ("h+pi", heading + math.pi)):
    d = angdiff(v, ref)
    if abs(d) < 0.5:
      print(f"  +0x{off:03x} = {v:.3f}  ({label} {math.degrees(d):+.1f} deg)")


