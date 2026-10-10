#!/usr/bin/env python3
"""Set a hardware WRITE watchpoint on the player's X-velocity field
(PlayerBase + 0xb8) and report the EIP (and surrounding code bytes) every
time something writes to it. Move the left stick left/right while this
runs - the EIP printed on each hit is the actual instruction responsible,
which you can look up directly in Ghidra instead of guessing from static
xrefs.

DAT_004eaa04 is a pointer VARIABLE (its value is the player object's
address, which can change between sessions), so this script dereferences
it fresh at startup rather than hardcoding a watch address.

Usage:
    python3 watch_velocity_write.py [num_hits] [--offset 0xb8] [--field-size 4]

    num_hits: how many writes to catch before stopping (default 15)
    --offset: which field to watch, relative to PlayerBase (default 0xb8,
        X-velocity). Use 0xc0 to instead watch Z-velocity.
"""

import argparse
import sys

sys.path.insert(0, ".")
from gdb_rsp import ( # noqa: E402
    connect,
    read_memory,
    set_watchpoint,
    remove_watchpoint,
    wait_for_stop,
    read_all_registers,
    parse_registers,
    send_packet,
)

PLAYER_BASE_PTR_ADDR = 0x004EAA04


def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("num_hits", nargs="?", type=int, default=15)
  parser.add_argument("--offset", type=lambda x: int(x, 0), default=0xB8)
  parser.add_argument("--field-size", type=int, default=4)
  args = parser.parse_args()

  sock = connect()

  player_base_bytes = read_memory(sock, PLAYER_BASE_PTR_ADDR, 4)
  player_base = int.from_bytes(player_base_bytes, byteorder="little")
  if player_base == 0:
    print(f"DAT_004eaa04 is currently 0 (no player object) - load into a level first, then re-run.")
    sys.exit(1)

  watch_addr = player_base + args.offset
  print(f"Player base: 0x{player_base:08x}")
  print(f"Watching 0x{watch_addr:08x} (base + 0x{args.offset:x}) for writes, {args.field_size} bytes")

  set_watchpoint(sock, watch_addr, args.field_size, kind=b"2")

  try:
    for i in range(args.num_hits):
      print(f"\n--- waiting for write {i + 1}/{args.num_hits} (move the stick now) ---")
      send_packet(sock, b"c")

      stop_payload = wait_for_stop(sock)
      print(f"Stopped: {stop_payload.decode(errors='replace')}")

      hex_regs = read_all_registers(sock)
      regs = parse_registers(hex_regs)
      eip = regs.get("eip")

      if eip is None:
        print("  Could not read EIP from stop reply.")
        continue

      print(f"  EIP (instruction that wrote the field): 0x{eip:08x}")

      try:
        code = read_memory(sock, max(0, eip - 16), 32)
        print(f"  code bytes @ (EIP-16 .. EIP+16): {code.hex()}")
        print(f"  -> look up 0x{eip:08x} directly in Ghidra's listing to see the containing function/instruction")

      except Exception as e:
        print(f"  code read failed: {e}")

      try:
        field_val = read_memory(sock, watch_addr, args.field_size)
        print(f"  new value at 0x{watch_addr:08x}: {field_val.hex()}")

      except Exception as e:
        print(f"  field read failed: {e}")

  except KeyboardInterrupt:
    print("\nStopped by user.")

  finally:
    try:
      remove_watchpoint(sock, watch_addr, args.field_size, kind=b"2")
    except Exception as e:
      print(f"(failed to remove watchpoint cleanly: {e})")


if __name__ == "__main__":
  main()
