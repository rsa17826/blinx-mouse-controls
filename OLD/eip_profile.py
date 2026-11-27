#!/usr/bin/env python3
"""Sample where the guest CPU spends its time (run during a save/load screen).

Usage:
    python3 eip_profile.py <samples> <interval_ms>

Each sample lets the guest run for <interval_ms>, interrupts it, and records EIP
plus the first stack dword that looks like a return address into game code (a
heuristic: it can pick stale stack values). Prints a summary by region, the top
EIPs, and the top guessed callers.
"""

import collections
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from gdb_rsp import ( # noqa: E402
  connect,
  send_packet,
  wait_for_stop,
  read_all_registers,
  parse_registers,
  read_memory,
)

CODE_LO = 0x10000
CODE_HI = 0x1D8000
KERNEL_LO = 0x80000000


def region(addr):
  if addr >= KERNEL_LO:
    return "kernel"

  if CODE_LO <= addr < CODE_HI:
    return "game code"

  return "other"


def main():
  samples = int(sys.argv[1])
  interval = int(sys.argv[2]) / 1000.0

  sock = connect()
  eips = collections.Counter()
  callers = collections.Counter()
  regions = collections.Counter()
  unreadable_stacks = 0
  try:
    for _ in range(samples):
      send_packet(sock, b"c")
      time.sleep(interval)
      sock.sendall(b"\x03")
      wait_for_stop(sock)
      regs = parse_registers(read_all_registers(sock))
      eips[regs["eip"]] += 1
      regions[region(regs["eip"])] += 1
      stack_len = min(256, 0x1000 - (regs["esp"] & 0xFFF))
      try:
        stack = read_memory(sock, regs["esp"], stack_len)

      except RuntimeError:
        unreadable_stacks += 1
        continue

      for off in range(0, len(stack) - 3, 4):
        value = int.from_bytes(stack[off : off + 4], "little")
        if CODE_LO <= value < CODE_HI:
          callers[value] += 1
          break




  finally:
    send_packet(sock, b"c")
    sock.close()

  print(f"{samples} samples")
  for name, n in regions.most_common():
    print(f"  {name}: {n} ({100 * n / samples:.0f}%)")

  print(f"  samples with an unreadable stack: {unreadable_stacks}")
  print("top EIPs:")
  for addr, n in eips.most_common(15):
    print(f"  0x{addr:08x}: {n}")

  print("top guessed callers (game code):")
  for addr, n in callers.most_common(15):
    print(f"  0x{addr:08x}: {n}")


if __name__ == "__main__":
  main()
