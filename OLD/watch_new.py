#!/usr/bin/env python3
"""Two-phase watchpoint: learn which EIPs fire normally, then report only new ones.

Phase 1 (baseline): the guest runs normally
is recorded as "normal". Do NOT trigger the thing you are looking for.
Phase 2 (trigger): trigger it. Only EIPs not seen in phase 1 are reported, once
each, with registers and the code just before the EIP.

Usage (run from the project root):
    python3 lib/watch_new.py <hex_addr> <length> <kind: 2 write, 3 read, 4 access> <baseline_seconds> <trigger_seconds>

Example:
    python3 lib/watch_new.py 0x4eaaac 4 3 15 20

"""

import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gdb_rsp import ( # noqa: E402
  I386_REG_NAMES,
  cmd_continue,
  connect,
  parse_registers,
  read_all_registers,
  read_memory,
  remove_watchpoint,
  send_packet,
  set_watchpoint,
  try_read,
  wait_for_stop,
)


def main():
  if len(sys.argv) != 6:
    print(__doc__)
    sys.exit(1)

  addr = int(sys.argv[1], 16)
  length = int(sys.argv[2])
  kind = sys.argv[3].encode()
  baseline_s = float(sys.argv[4])
  trigger_s = float(sys.argv[5])

  sock = connect()
  set_watchpoint(sock, addr, length, kind=kind)

  start = time.time()
  baseline_end = start + baseline_s
  end = baseline_end + trigger_s
  seen = {}
  reported = {}
  running = False
  announced = False

  print(f"Baseline for {baseline_s:.0f}s: do NOT trigger anything.")
  try:
    while time.time() < end:
      if not announced and time.time() >= baseline_end:
        print(f"\n>>> TRIGGER NOW (for {trigger_s:.0f}s). {len(seen)} normal EIPs learned.\n")
        announced = True

      if not running:
        send_packet(sock, b"c")
        running = True

      sock.settimeout(0.2)
      try:
        wait_for_stop(sock)

      except socket.timeout:
        continue

      finally:
        sock.settimeout(None)

      running = False
      regs = parse_registers(read_all_registers(sock))
      eip = regs["eip"]
      if time.time() < baseline_end:
        if eip not in seen:
          seen[eip] = read_memory(sock, eip - 32, 64)

        continue

      if eip in seen or eip in reported:
        continue

      reported[eip] = True
      print(f"=== NEW EIP 0x{eip:08x} ===")
      print("  regs: " + " ".join(f"{n}={regs[n]:08x}" for n in I386_REG_NAMES[:8]))
      print(f"  code @ EIP-32: {read_memory(sock, eip - 32, 64).hex()}")
      for name in ["eax", "ecx", "edx", "ebx", "esi", "edi", "ebp"]:
        data = try_read(sock, regs[name], 32)
        if data is not None:
          print(f"  [{name}=0x{regs[name]:08x}]: {data.hex()}")




  finally:
    if running:
      sock.sendall(b"\x03")
      wait_for_stop(sock)

    remove_watchpoint(sock, addr, length, kind=kind)
    cmd_continue(sock)

  print("\nNormal (baseline) EIPs:")
  for eip, code in sorted(seen.items()):
    print(f"  0x{eip:08x}  code @ EIP-32: {code.hex()}")

  print(f"\nDone. {len(seen)} normal EIPs, {len(reported)} new.")
  for eip in sorted(reported):
    print(f"  new: 0x{eip:08x}")


if __name__ == "__main__":
  main()
