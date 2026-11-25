#!/usr/bin/env python3
"""Sample the guest CPU and print the most common call chains.

Usage:
    python3 eip_chains.py <samples> <interval_ms> [depth]

Frames are recovered by scanning the stack for dwords inside game code whose
preceding bytes look like a call instruction (e8 rel32, ff 15 abs32, ff d0-d7,
ff /2 with a register or register+displacement operand). This is a heuristic:
it can include stale stack values, so treat deep frames with care.
"""
import collections
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from gdb_rsp import (  # noqa: E402
  connect,
  send_packet,
  wait_for_stop,
  read_all_registers,
  parse_registers,
  read_memory,
)

CODE_LO = 0x10000
CODE_HI = 0x1D8000
STACK_BYTES = 1024


def read_stack(sock, esp, total):
  data = b""
  addr = esp
  while len(data) < total:
    n = min(total - len(data), 0x1000 - (addr & 0xFFF))
    try:
      data += read_memory(sock, addr, n)
    except RuntimeError:
      break
    addr += n
  return data


def looks_like_call_return(sock, addr):
  prev = read_memory(sock, addr - 8, 8)  # bytes addr-8 .. addr-1
  if prev[3] == 0xE8:
    return True
  if prev[2] == 0xFF and prev[3] == 0x15:
    return True
  if prev[2] == 0xFF and 0x90 <= prev[3] <= 0x97:
    return True
  if prev[5] == 0xFF and 0x50 <= prev[6] <= 0x57:
    return True
  if prev[6] == 0xFF and (0xD0 <= prev[7] <= 0xD7 or prev[7] in (0x10, 0x11, 0x12, 0x13, 0x16, 0x17)):
    return True
  return False


def main():
  samples = int(sys.argv[1])
  interval = int(sys.argv[2]) / 1000.0
  depth = int(sys.argv[3]) if len(sys.argv) > 3 else 6

  sock = connect()
  chains = collections.Counter()
  try:
    for _ in range(samples):
      send_packet(sock, b"c")
      time.sleep(interval)
      sock.sendall(b"\x03")
      wait_for_stop(sock)
      regs = parse_registers(read_all_registers(sock))
      chain = [regs["eip"]]
      stack = read_stack(sock, regs["esp"], STACK_BYTES)
      for off in range(0, len(stack) - 3, 4):
        if len(chain) > depth:
          break
        value = int.from_bytes(stack[off : off + 4], "little")
        if CODE_LO + 8 <= value < CODE_HI and looks_like_call_return(sock, value):
          chain.append(value)
      chains[tuple(chain)] += 1

  finally:
    send_packet(sock, b"c")
    sock.close()

  print(f"{samples} samples; top chains (EIP <- return addresses):")
  for chain, n in chains.most_common(12):
    print(f"  {n:3d}  " + " <- ".join(f"0x{a:08x}" for a in chain))


if __name__ == "__main__":
  main()
