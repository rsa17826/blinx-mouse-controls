#!/usr/bin/env python3
"""Add Time Crystals to the IL (in-level) or OOL (out-of-level)
inventory, in a specified order and quantity per type.

Usage:
    python3 settime.py --il|--ool [--replace] <type> <qty> [<type> <qty> ...]

Types: null pause slow ff rew rec

--replace resets the count to 0 first, so the given additions become
the entire inventory instead of being appended after what's already
there.

Example:
    python3 settime.py --ool rec 3 ff 2 pause 1 rew 3 pause 1
    (adds 3 rec, then 2 ff, then 1 pause, then 3 rew, then 1 more
    pause, in that exact order, appended after whatever is already
    in the inventory)

    python3 settime.py --ool --replace pause 7 ff 2 rec 1
    (clears the inventory first, then sets it to exactly this)

Each addition writes a (type_id, 0x0a) pair into the next free slot
and increments the struct's count byte. The struct holds a maximum
of 10 entries (the game fails to load a level if this is exceeded),
so this script stops with a clear error rather than silently
truncating if the requested additions would overflow it.

Requires xemu running with the gdbstub enabled (-s) and gdb_rsp.py
in the same directory.
"""

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../lib')))
import gdb_rsp

TYPE_MAP = {
  "null": 1,
  "pause": 2,
  "slow": 3,
  "ff": 4,
  "rew": 5,
  "rec": 6,
}

MARKER_BYTE = 0x0A
MAX_SLOTS = 10

# (count_addr, array_addr) for each inventory instance
STRUCTS = {
  "il": {"count_addr": 0x0050969A, "array_addr": 0x0050969B},
  "ool": {"count_addr": 0x009E373C, "array_addr": 0x009E3728},
}


def parse_additions(args):
  """Parse ['rec', '3', 'ff', '2', ...] into [(type_id, qty), ...],
  preserving order. Raises ValueError on bad input rather than
  silently skipping or defaulting anything."""
  if len(args) % 2 != 0:
    raise ValueError(f"Expected pairs of <type> <qty>, got an odd number of arguments ({len(args)}): {args}")

  additions = []
  for i in range(0, len(args), 2):
    type_name = args[i]
    qty_str = args[i + 1]

    if type_name not in TYPE_MAP:
      raise ValueError(f"Unknown type {type_name!r} - must be one of {sorted(TYPE_MAP.keys())}")

    try:
      qty = int(qty_str)

    except ValueError:
      raise ValueError(f"Quantity for {type_name!r} must be an integer, got {qty_str!r}")

    if qty <= 0:
      raise ValueError(f"Quantity for {type_name!r} must be positive, got {qty}")

    additions.append((TYPE_MAP[type_name], qty))

  return additions


def add_crystals(sock, struct_key, additions, replace=False):
  struct = STRUCTS[struct_key]
  count_addr = struct["count_addr"]
  array_addr = struct["array_addr"]

  current_count = gdb_rsp.read_memory(sock, count_addr, 1)[0]
  print(f"[{struct_key}] Current count: {current_count}")

  if replace:
    current_count = 0
    gdb_rsp.write_memory(sock, count_addr, bytes([current_count]))
    print(f"[{struct_key}] --replace: reset count to 0 before adding")

  total_requested = sum(qty for _, qty in additions)
  if current_count + total_requested > MAX_SLOTS:
    raise RuntimeError(f"Cannot add {total_requested} crystal(s): current count ({current_count}) + requested ({total_requested}) = {current_count + total_requested}, which exceeds the struct's max of {MAX_SLOTS} slots. Nothing was written.")

  for type_id, qty in additions:
    type_name = next(n for n, tid in TYPE_MAP.items() if tid == type_id)
    for _ in range(qty):
      slot_addr = array_addr + current_count * 2
      gdb_rsp.write_memory(sock, slot_addr, bytes([type_id, MARKER_BYTE]))
      current_count += 1
      gdb_rsp.write_memory(sock, count_addr, bytes([current_count]))
      print(f"  added {type_name} (type {type_id}) at slot {current_count - 1} (0x{slot_addr:08x}) - count now {current_count}")


  print(f"[{struct_key}] Final count: {current_count}")


if __name__ == "__main__":
  argv = sys.argv[1:]

  if "--il" in argv:
    struct_key = "il"
    argv.remove("--il")
  elif "--ool" in argv:
    struct_key = "ool"
    argv.remove("--ool")
  else:
    struct_key = "both"


  replace = "--replace" in argv
  if replace:
    argv.remove("--replace")

  if not argv:
    print(__doc__)
    sys.exit(1)

  additions = parse_additions(argv)

  sock = gdb_rsp.connect()
  try:
    if struct_key == "both":
      add_crystals(sock, "il", additions, replace=replace)
      add_crystals(sock, "ool", additions, replace=replace)
    else:
      add_crystals(sock, struct_key, additions, replace=replace)


  finally:
    gdb_rsp.cmd_continue(sock)

