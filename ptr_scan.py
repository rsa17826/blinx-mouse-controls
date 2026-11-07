#!/usr/bin/env python3
"""Pointer scanner for xemu guest RAM (uses the guest page tables).

Usage:
    python3 ptr_scan.py find <hex_value> <out_file> [--back N] [--ram-mb M]
    python3 ptr_scan.py common <file_a> <file_b>
    python3 ptr_scan.py refs <hex_value> [--ram-mb M]
    python3 ptr_scan.py chain <hex_value> [--back N] [--depth D] [--static-max HEX] [--limit L] [--ram-mb M]

<hex_value> is a guest virtual address (translated through the page tables) or a
0xF0xxxxxx alias (physical + 0xF0000000). Pointers are searched in every form
the guest uses for that physical byte: the alias plus each virtual mapping.

--back N also accepts pointers up to N bytes BELOW the target (interior
pointers: the pointer holds an object's start and the target is a field in it).

find   : list every 4-byte-aligned word in RAM that points at the value.
common : intersect two `find` outputs (one per state). A holder address
         present in both is a stable pointer.
refs   : search for the address bytes at ANY alignment (immediates in code).
chain  : follow holders of holders, up to D levels, and print every chain that
         ends in the static data area (virtual address below --static-max,
         default 0xc00000).

RAM is read as physical pages 0..M MB (default 64) through 0xF0000000 + physical.
"""
import argparse
import array
import os
import re
import struct
import sys

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from fastmem import FastMemWriter  # noqa: E402

ALIAS_BASE = 0xF0000000
PAGE = 0x1000
MAPPER = None


class Mapper:
  """Physical <-> virtual translation from the guest page tables (32-bit, non-PAE)."""

  def __init__(self, mem):
    self.small = {}  # physical page base -> [virtual page base]
    self.v2p = {}  # virtual page base -> physical page base
    self.big = []  # (virtual base, physical base) for 4 MB pages
    self.unreadable = 0
    pd = struct.unpack("<1024I", mem.read(ALIAS_BASE + (mem.cr3 & ~0xFFF), PAGE))
    for pdi, pde in enumerate(pd):
      if not pde & 1:
        continue
      if pde & 0x80:
        self.big.append((pdi << 22, pde & 0xFFC00000))
        continue
      try:
        pt = struct.unpack("<1024I", mem.read(ALIAS_BASE + (pde & ~0xFFF), PAGE))
      except RuntimeError:
        self.unreadable += 1
        continue
      for pti, pte in enumerate(pt):
        if pte & 1:
          vpage = (pdi << 22) + (pti << 12)
          self.small.setdefault(pte & ~0xFFF, []).append(vpage)
          self.v2p[vpage] = pte & ~0xFFF

  def virtuals(self, phys):
    out = [v + (phys & 0xFFF) for v in self.small.get(phys & ~0xFFF, [])]
    out += [vb + phys - pb for vb, pb in self.big if pb <= phys < pb + 0x400000]
    return sorted(out)

  def to_phys(self, value):
    if value >= ALIAS_BASE:
      return value - ALIAS_BASE
    vpage = value & ~0xFFF
    if vpage in self.v2p:
      return self.v2p[vpage] + (value & 0xFFF)
    for vb, pb in self.big:
      if vb <= value < vb + 0x400000:
        return pb + value - vb
    raise RuntimeError(f"virtual 0x{value:x} is not mapped by the guest page tables")


def to_phys(value):
  return MAPPER.to_phys(value)


def forms(phys):
  return [ALIAS_BASE + phys] + MAPPER.virtuals(phys)


def fmt(phys):
  virtuals = MAPPER.virtuals(phys)
  return f"0x{virtuals[0]:x}" if virtuals else f"0x{ALIAS_BASE + phys:08x}"


def load_ram(ram_mb):
  global MAPPER
  size = ram_mb * 0x100000
  words = array.array("I")
  if words.itemsize != 4:
    raise RuntimeError("array('I') is not 4 bytes on this platform")
  skipped = []
  mem = FastMemWriter()
  try:
    for phys in range(0, size, PAGE):
      try:
        data = mem.read(ALIAS_BASE + phys, PAGE)
      except RuntimeError as err:
        skipped.append((phys, str(err)))
        data = bytes(PAGE)
      if len(data) != PAGE:
        raise RuntimeError(f"short read at physical 0x{phys:x}: {len(data)} bytes")
      words.frombytes(data)
    MAPPER = Mapper(mem)
  finally:
    mem.close()

  total = size // PAGE
  print(f"read {ram_mb} MB; {len(skipped)} of {total} page(s) unreadable")
  if skipped:
    print(f"  first unreadable: physical 0x{skipped[0][0]:x}: {skipped[0][1]}")
  if len(skipped) == total:
    raise RuntimeError("no page could be read through the 0xF0000000 window")
  print(f"page tables: {len(MAPPER.v2p)} small mapping(s), {len(MAPPER.big)} large, {MAPPER.unreadable} table(s) unreadable")
  return words


def find_holders(words, targets, back):
  """Return [(holder_phys, word, target_phys, delta)] where word + delta == target."""
  accepted = {}
  for t in targets:
    for f in forms(t):
      for d in range(back + 1):
        accepted[(f - d) & 0xFFFFFFFF] = (t, d)
  hits = []
  for i, w in enumerate(words):
    found = accepted.get(w)
    if found is not None:
      hits.append((i * 4, w, found[0], found[1]))
  return hits


def cmd_find(args):
  words = load_ram(args.ram_mb)
  target = to_phys(int(args.value, 16))
  hits = find_holders(words, [target], args.back)
  with open(args.out_file, "w") as f:
    for holder, w, _, delta in hits:
      f.write(f"0x{ALIAS_BASE + holder:08x}\n")
      print(f"  holder {fmt(holder)} (alias 0x{ALIAS_BASE + holder:08x}) = 0x{w:08x}, +{delta:#x} to target")
  print(f"{len(hits)} holder(s) of {fmt(target)} (physical 0x{target:x}); saved to {args.out_file}")


def cmd_common(args):
  def load(path):
    with open(path) as f:
      lines = [line.strip() for line in f if line.strip()]
    bad = [line for line in lines if not re.fullmatch(r"0x[0-9a-f]{8}", line)]
    if bad:
      raise RuntimeError(f"{path}: not an address line: {bad[0]!r} (use the out_file written by `find`, not saved console output)")
    return set(lines)

  both = sorted(load(args.file_a) & load(args.file_b))
  for addr in both:
    print(f"  {addr}")
  print(f"{len(both)} address(es) hold a pointer in both states")


def cmd_refs(args):
  data = load_ram(args.ram_mb).tobytes()
  target = to_phys(int(args.value, 16))
  count = 0
  for form in forms(target):
    pattern = form.to_bytes(4, "little")
    pos = data.find(pattern)
    while pos != -1:
      count += 1
      before = data[max(0, pos - 3) : pos].hex()
      tag = "  (unaligned)" if pos % 4 else ""
      print(f"  {fmt(pos)} (alias 0x{ALIAS_BASE + pos:08x}) holds 0x{form:08x}, preceded by {before}{tag}")
      pos = data.find(pattern, pos + 1)
  print(f"{count} occurrence(s) of the address bytes (any alignment) for {fmt(target)}")


def cmd_chain(args):
  words = load_ram(args.ram_mb)
  start = to_phys(int(args.value, 16))
  static_max = int(args.static_max, 16)
  level = [(start, [])]
  for depth in range(1, args.depth + 1):
    paths = {t: p for t, p in level}
    hits = find_holders(words, list(paths), args.back)
    next_level = []
    statics = 0
    for holder, _, target, delta in hits:
      path = paths[target] + [(holder, delta)]
      virtuals = MAPPER.virtuals(holder)
      if virtuals and virtuals[0] < static_max:
        statics += 1
        parts = [f"[{fmt(h)}] +{d:#x}" for h, d in reversed(path)]
        print("  STATIC: " + " -> ".join(parts) + f" -> {fmt(start)}")
      else:
        next_level.append((holder, path))
    level = next_level[: args.limit]
    print(f"depth {depth}: {len(hits)} holder(s), {statics} static, following {len(level)}")
    if not level:
      break


def number(text):
  return int(text, 0)


def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = parser.add_subparsers(dest="cmd", required=True)

  p = sub.add_parser("find")
  p.add_argument("value")
  p.add_argument("out_file")
  p.add_argument("--back", type=number, default=0)
  p.add_argument("--ram-mb", type=number, default=64)
  p.set_defaults(fn=cmd_find)

  p = sub.add_parser("common")
  p.add_argument("file_a")
  p.add_argument("file_b")
  p.set_defaults(fn=cmd_common)

  p = sub.add_parser("refs")
  p.add_argument("value")
  p.add_argument("--ram-mb", type=number, default=64)
  p.set_defaults(fn=cmd_refs)

  p = sub.add_parser("chain")
  p.add_argument("value")
  p.add_argument("--back", type=number, default=0)
  p.add_argument("--depth", type=number, default=3)
  p.add_argument("--static-max", default="0xc00000")
  p.add_argument("--limit", type=number, default=50)
  p.add_argument("--ram-mb", type=number, default=64)
  p.set_defaults(fn=cmd_chain)

  args = parser.parse_args()
  args.fn(args)


if __name__ == "__main__":
  main()
