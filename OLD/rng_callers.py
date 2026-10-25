#!/usr/bin/env python3
"""Count return addresses of calls to the game's randomiser (0x126d5d).

Usage:
    python3 rng_callers.py <num_hits>

Hold the fire button while it runs. Run it twice (fast-forward off, then on)
and compare which callers only show up when the shot offset happens.
"""

import collections
import sys

sys.path.insert(0, ".")
from gdb_rsp import (
  connect,
  send_packet,
  recv_ack_or_packet,
  wait_for_stop,
  read_memory,
  read_all_registers,
  parse_registers,
  cmd_continue,
)

RNG_ENTRY = 0x00126D5D

hits = int(sys.argv[1])
sock = connect()
send_packet(sock, f"Z0,{RNG_ENTRY:x},1".encode())
reply = recv_ack_or_packet(sock)
if reply != b"OK":
  raise RuntimeError(f"Failed to set breakpoint: {reply}")

callers = collections.Counter()
try:
  for _ in range(hits):
    send_packet(sock, b"c")
    wait_for_stop(sock)
    regs = parse_registers(read_all_registers(sock))
    ret = int.from_bytes(read_memory(sock, regs["esp"], 4), "little")
    callers[ret] += 1


except KeyboardInterrupt:
  print("\nInterrupted.")
  sock.sendall(b"\x03")
  wait_for_stop(sock)

finally:
  send_packet(sock, f"z0,{RNG_ENTRY:x},1".encode())
  recv_ack_or_packet(sock)
  cmd_continue(sock)
  sock.close()
  print("Return addresses:")
  for ret, n in callers.most_common():
    print(f"  0x{ret:08x}: {n}")

