#!/usr/bin/env python3
"""list every guest virtual address that maps to the same physical byte.

Usage:
    python3 find_aliases.py <hex_address>

<hex_address> may be a plain virtual address, the 0xF0xxxxxx alias or the
0x80xxxxxx kernel alias (same conversions as ptr_scan.py). The page tables are
walked from the guest's CR3 (32-bit, non-PAE). Page-table pages are read through
the 0xF0000000 window, so only tables inside RAM are readable; any that are not
are counted and reported.
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from fastmem import FastMemWriter # noqa: E402

PHYS_OFFSET = 0xAF000
ALIAS_BASE = 0xF0000000
KERNEL_BASE = 0x80000000


def to_phys(value):
  if value >= ALIAS_BASE:
    return value - ALIAS_BASE

  if value >= KERNEL_BASE:
    return value - KERNEL_BASE

  return value + PHYS_OFFSET


def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("value")
  args = parser.parse_args()
  target = to_phys(int(args.value, 16))

  found = []
  unreadable = []
  mem = FastMemWriter()
  try:
    pd = struct.unpack("<1024I", mem.read(ALIAS_BASE + (mem.cr3 & ~0xFFF), 4096))
    for pdi, pde in enumerate(pd):
      if not pde & 1:
        continue

      if pde & 0x80:
        base = pde & 0xFFC00000
        if base <= target < base + 0x400000:
          found.append(((pdi << 22) + (target - base), bool(pde & 2), "4MB page"))

        continue

      pt_phys = pde & ~0xFFF
      try:
        pt = struct.unpack("<1024I", mem.read(ALIAS_BASE + pt_phys, 4096))

      except RuntimeError as err:
        unreadable.append((pdi, pt_phys, str(err)))
        continue

      for pti, pte in enumerate(pt):
        if not pte & 1:
          continue

        base = pte & ~0xFFF
        if base <= target < base + 0x1000:
          writable = bool(pde & 2) and bool(pte & 2)
          found.append(((pdi << 22) + (pti << 12) + (target - base), writable, "4KB page"))




  finally:
    mem.close()

  print(f"physical 0x{target:x}")
  for virt, writable, kind in sorted(found):
    print(f"  virtual 0x{virt:08x}  {'writable' if writable else 'read-only'}  ({kind})")

  print(f"{len(found)} mapping(s); {len(unreadable)} page table(s) unreadable")
  if unreadable:
    print(f"  first unreadable: directory entry {unreadable[0][0]} at physical 0x{unreadable[0][1]:x}: {unreadable[0][2]}")


if __name__ == "__main__":
  main()
