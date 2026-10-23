#!/usr/bin/env python3
"""Disable the lock-on/auto-aim stores into player+0x140 (pitch) and player+0x144 (yaw).

Each `fstp dword ptr [esi+off]` (6 bytes) becomes `fstp st(0)` + 4 NOPs,
which keeps the x87 stack balanced. Both fields are then zeroed.
Refuses to write unless the original bytes match.
"""
import struct
import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../lib')))
from gdb_rsp import connect, read_memory, write_memory, cmd_continue

PLAYER = 0x004EAA20
# (address, expected original bytes, field offset in player object)
PATCHES = [
  (0x000DA118, bytes.fromhex("d99e40010000"), 0x140),
  (0x000DA134, bytes.fromhex("d99e44010000"), 0x144),
]
NEW = bytes.fromhex("ddd8") + b"\x90" * 4

sock = connect()
try:
  for addr, expected, _ in PATCHES:
    current = read_memory(sock, addr, len(expected))
    if current != expected:
      raise RuntimeError(f"Unexpected bytes at 0x{addr:x}: {current.hex()} (expected {expected.hex()})")

  for addr, expected, off in PATCHES:
    write_memory(sock, addr, NEW)
    if read_memory(sock, addr, len(NEW)) != NEW:
      raise RuntimeError(f"Write verification failed at 0x{addr:x}")
    write_memory(sock, PLAYER + off, struct.pack("<f", 0.0))
    print(f"patched 0x{addr:x}, zeroed player+0x{off:x}")
finally:
  cmd_continue(sock)
