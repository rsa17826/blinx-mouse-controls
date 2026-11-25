#!/usr/bin/env python3
"""Break on a function and print the call chain at each hit.

Usage:
    python3 break_chain.py <hex_function_address> <hits> [depth]

The address must be the function's first instruction (take it from Ghidra, for
example XAPILIB::WriteFile, XAPILIB::CreateFile or an XCreateSaveGame entry).
At entry [esp] is the true return address; deeper frames are recovered with the
same call-instruction heuristic as eip_chains.py. Ctrl-C stops early.
"""
import collections
import os
import sys

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from gdb_rsp import (  # noqa: E402
  connect,
  send_packet,
  recv_ack_or_packet,
  wait_for_stop,
  read_all_registers,
  parse_registers,
  cmd_continue,
)
from eip_chains import read_stack, looks_like_call_return, CODE_LO, CODE_HI, STACK_BYTES  # noqa: E402


def main():
  addr = int(sys.argv[1], 16)
  hits = int(sys.argv[2])
  depth = int(sys.argv[3]) if len(sys.argv) > 3 else 6

  sock = connect()
  send_packet(sock, f"Z0,{addr:x},1".encode())
  reply = recv_ack_or_packet(sock)
  if reply != b"OK":
    raise RuntimeError(f"Failed to set breakpoint: {reply}")

  chains = collections.Counter()
  running = False
  try:
    for i in range(hits):
      send_packet(sock, b"c")
      running = True
      wait_for_stop(sock)
      running = False
      regs = parse_registers(read_all_registers(sock))
      stack = read_stack(sock, regs["esp"], STACK_BYTES)
      chain = []
      for off in range(0, len(stack) - 3, 4):
        if len(chain) >= depth:
          break
        value = int.from_bytes(stack[off : off + 4], "little")
        if off == 0 or (CODE_LO + 8 <= value < CODE_HI and looks_like_call_return(sock, value)):
          chain.append(value)
      chains[tuple(chain)] += 1
      print(f"hit {i + 1}: " + " <- ".join(f"0x{a:08x}" for a in chain))

  except KeyboardInterrupt:
    print("\nInterrupted.")
    if running:
      sock.sendall(b"\x03")
      wait_for_stop(sock)

  finally:
    send_packet(sock, f"z0,{addr:x},1".encode())
    recv_ack_or_packet(sock)
    cmd_continue(sock)
    sock.close()

  print("distinct chains:")
  for chain, n in chains.most_common(10):
    print(f"  {n:3d}  " + " <- ".join(f"0x{a:08x}" for a in chain))


if __name__ == "__main__":
  main()
