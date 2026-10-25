#!/usr/bin/env python3
"""Scan a virtual address range for a run of zero bytes long enough to
host our trampoline (code + 8 bytes of scratch floats). Run this near
the hook site (0x232dd) so the jmp's rel32 displacement stays small
and easy to sanity-check by eye, though a full 32-bit range works too.

Usage:
    python3 find_cave.py [<hex_start> <hex_end>] [<min_size_decimal>]

Defaults to scanning a window around the known code (since NOP/00
padding between functions is common in compiled binaries), from
0x00000000 to 0x00100000, looking for at least 64 free bytes.
"""

import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory, cmd_continue # noqa: E402

DEFAULT_START = 0x00000000
DEFAULT_END = 0x200000
DEFAULT_MIN_SIZE = 64
CHUNK = 0x1000


def find_zero_runs(sock, start, end, min_size):
  addr = start
  run_start = None
  run_len = 0
  found = []

  while addr < end:
    length = min(CHUNK, end - addr)
    try:
      chunk = read_memory(sock, addr, length)

    except RuntimeError:
      # Unmapped page - breaks any in-progress run, skip ahead.
      if run_len >= min_size:
        found.append((run_start, run_len))

      run_start = None
      run_len = 0
      addr += length
      continue

    for i, b in enumerate(chunk):
      cur = addr + i
      if b == 0:
        if run_start is None:
          run_start = cur
          run_len = 1
        else:
          run_len += 1

      else:
        if run_len >= min_size:
          found.append((run_start, run_len))

        run_start = None
        run_len = 0


    addr += length

  if run_len >= min_size:
    found.append((run_start, run_len))

  return found


def main():
  start = int(sys.argv[1], 16) if len(sys.argv) > 1 else DEFAULT_START
  end = int(sys.argv[2], 16) if len(sys.argv) > 2 else DEFAULT_END
  min_size = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_MIN_SIZE

  print(f"Scanning 0x{start:08x}-0x{end:08x} for zero-runs >= {min_size} bytes...")
  sock = connect()
  runs = find_zero_runs(sock, start, end, min_size)
  cmd_continue(sock)

  if not runs:
    print("No suitable cave found in this range. Try a wider range or a smaller min_size.")
    return

  print(f"Found {len(runs)} candidate cave(s):")
  for addr, size in runs:
    print(f"  0x{addr:08x}  ({size} bytes)")

  print("\nNOTE: a run of zero bytes might just be zeroed DATA, not unused code space - verify the region is inside an executable code segment before trusting it, and prefer a cave close to 0x232dd if possible to keep the jmp simple.")


if __name__ == "__main__":
  main()
