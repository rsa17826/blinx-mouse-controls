#!/usr/bin/env python3
"""Disable the player-heading store inside the yaw trampoline (test only)."""
import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory, write_memory, cmd_continue

TRAMPOLINE = 0x00141F25 # cave 0x141ee5 + 64
OLD = bytes.fromhex("d95824")
NEW = bytes.fromhex("ddd890")

sock = connect()
code = read_memory(sock, TRAMPOLINE, 64)
if code.count(OLD) != 1:
  cmd_continue(sock)
  raise RuntimeError(f"expected exactly one {OLD.hex()} in yaw trampoline, found {code.count(OLD)}: {code.hex()}")

addr = TRAMPOLINE + code.index(OLD)
write_memory(sock, addr, NEW)
if read_memory(sock, addr, 3) != NEW:
  cmd_continue(sock)
  raise RuntimeError("write verification failed")

cmd_continue(sock)
print(f"heading store disabled at 0x{addr:x}")