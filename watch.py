#!/usr/bin/env python3
"""watch.py <addr_hex> <len>
Reads the window, then loops: change the inventory in-game, press
Enter, and it prints every byte that changed since the previous read.
Ctrl-C to stop."""

import sys

import gdb_rsp

addr = int(sys.argv[1], 16)
length = int(sys.argv[2])


def read_window():
  sock = gdb_rsp.connect()
  try:
    gdb_rsp.send_packet(sock, f"m{addr:x},{length:x}".encode())
    while True:
      payload = gdb_rsp.recv_ack_or_packet(sock)
      if payload[:1] in (b"T", b"S"):
        continue # stop notification from attaching, not our reply

      if payload.startswith(b"E"):
        raise RuntimeError(f"Read failed: {payload}")

      return bytes.fromhex(payload.decode())


  finally:
    gdb_rsp.cmd_continue(sock)
    sock.close() # the stub serves one client, so release it


prev = read_window()
print("baseline taken")
while True:
  input("change inventory, press Enter... ")
  cur = read_window()
  for i in range(length):
    if cur[i] != prev[i]:
      print(f"  0x{addr + i:08x} (+{i}): {prev[i]:02x} -> {cur[i]:02x}")


  print("--")
  prev = cur
