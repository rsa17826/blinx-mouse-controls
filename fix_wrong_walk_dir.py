#!/usr/bin/env python3
"""Disable the game's facing write [esi+0x8c] = eax at 0xd5680 (6 bytes -> NOPs)."""
import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory, write_memory, cmd_continue

ADDR = 0x000D5680
EXPECTED = bytes.fromhex("89868c000000")

sock = connect()
current = read_memory(sock, ADDR, len(EXPECTED))
if current != EXPECTED:
  cmd_continue(sock)
  raise RuntimeError(f"Unexpected bytes at 0x{ADDR:x}: {current.hex()}")

write_memory(sock, ADDR, b"\x90" * len(EXPECTED))
if read_memory(sock, ADDR, len(EXPECTED)) != b"\x90" * len(EXPECTED):
  cmd_continue(sock)
  raise RuntimeError("Write verification failed")

cmd_continue(sock)
print("Facing write disabled.")
