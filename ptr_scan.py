#!/usr/bin/env python3
"""Pointer scanner for xemu guest RAM (reads through the 0xF0000000 window).

Usage:
    python3 ptr_scan.py find <hex_value> <out_file> [--back N] [--ram-mb M]
    python3 ptr_scan.py common <file_a> <file_b>
    python3 ptr_scan.py refs <hex_value> [--ram-mb M]
    python3 ptr_scan.py chain <hex_value> [--back N] [--depth D] [--static-max HEX] [--limit L] [--ram-mb M]

<hex_value> may be a plain virtual address (0xa2e74d), the 0xF0xxxxxx alias
(0xf0add74d) or the 0x80xxxxxx kernel alias. Pointers are searched in all three
forms. Numbers accept hex (0x40) or decimal.

--back N also accepts pointers up to N bytes BELOW the target (interior
pointers: the pointer holds an object's start and the target is a field in it).

find   : list every 4-byte-aligned word in RAM that points at the value.
common : intersect two `find` outputs (one for the old value in the old state,
         one for the new value in the new state). A holder address present in
         both is a stable pointer.
chain  : follow holders of holders, up to D levels, and print every chain that
         ends in the static data area (plain virtual address below
         --static-max, default 0xc00000).

Plain virtual = physical - 0xAF000 (the offset the other scripts use). RAM is
read as physical pages 0..M MB (default 64) at 0xF0000000 + physical.
"""
import argparse
import array
import os
import re
import sys

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from fastmem import FastMemWriter  # noqa: E402

PHYS_OFFSET = 0xAF000
ALIAS_BASE = 0xF0000000
KERNEL_BASE = 0x80000000
PAGE = 0x1000


def number(text):
  return int(text, 0)


def to_phys(value):
  if value >= ALIAS_BASE:
    return value - ALIAS_BASE
  if value >= KERNEL_BASE:
    return value - KERNEL_BASE
  return value + PHYS_OFFSET


def forms(phys):
  out = [ALIAS_BASE + phys, KERNEL_BASE + phys]
  if phys >= PHYS_OFFSET:
    out.append(phys - PHYS_OFFSET)
  return out


def plain(phys):
  return phys - PHYS_OFFSET if phys >= PHYS_OFFSET else None


def fmt(phys):
  p = plain(phys)
  return f"0x{p:x}" if p is not None else f"0x{ALIAS_BASE + phys:08x}"


def load_ram(ram_mb):
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
  finally:
    mem.close()

  total = size // PAGE
  print(f"read {ram_mb} MB; {len(skipped)} of {total} page(s) unreadable")
  if skipped:
    print(f"  first unreadable: physical 0x{skipped[0][0]:x}: {skipped[0][1]}")
  if len(skipped) == total:
    raise RuntimeError("no page could be read through the 0xF0000000 window")
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
  target = to_phys(int(args.value, 16))
  hits = find_holders(load_ram(args.ram_mb), [target], args.back)
  with open(args.out_file, "w") as f:
    for holder, w, _, delta in hits:
      f.write(f"0x{ALIAS_BASE + holder:08x}\n")
      print(f"  holder {fmt(holder)} (alias 0x{ALIAS_BASE + holder:08x}) = 0x{w:08x}, +{delta:#x} to target")
  print(f"{len(hits)} holder(s) of {fmt(target)}; saved to {args.out_file}")


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


def cmd_chain(args):
  start = to_phys(int(args.value, 16))
  static_max = int(args.static_max, 16)
  words = load_ram(args.ram_mb)
  level = [(start, [])]
  for depth in range(1, args.depth + 1):
    paths = {t: p for t, p in level}
    hits = find_holders(words, list(paths), args.back)
    next_level = []
    statics = 0
    for holder, _, target, delta in hits:
      path = paths[target] + [(holder, delta)]
      p = plain(holder)
      if p is not None and p < static_max:
        statics += 1
        parts = [f"[{fmt(h)}] +{d:#x}" for h, d in reversed(path)]
        print("  STATIC: " + " -> ".join(parts) + f" -> {fmt(start)}")
      else:
        next_level.append((holder, path))
    level = next_level[: args.limit]
    print(f"depth {depth}: {len(hits)} holder(s), {statics} static, following {len(level)}")
    if not level:
      break


def cmd_refs(args):
  target = to_phys(int(args.value, 16))
  data = load_ram(args.ram_mb).tobytes()
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
  print(f"{count} occurrence(s) of the address bytes (any alignment)")


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

  p = sub.add_parser("chain")
  p.add_argument("value")
  p.add_argument("--back", type=number, default=0)
  p.add_argument("--depth", type=number, default=3)
  p.add_argument("--static-max", default="0xc00000")
  p.add_argument("--limit", type=number, default=50)
  p.add_argument("--ram-mb", type=number, default=64)
  p.set_defaults(fn=cmd_chain)

  p = sub.add_parser("refs")
  p.add_argument("value")
  p.add_argument("--ram-mb", type=number, default=64)
  p.set_defaults(fn=cmd_refs)

  args = parser.parse_args()
  args.fn(args)


if __name__ == "__main__":
  main()
