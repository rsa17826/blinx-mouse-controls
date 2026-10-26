#!/usr/bin/env python3
"""Find floats that change when fast-forward is toggled.

Usage:
    python3 ff_scan.py snap <ram_host_base_hex> <out_file>
    python3 ff_scan.py diff <snap_off> <snap_on>

Take one snapshot with fast-forward off and one with it on (same room, no
menus), then diff. Prints guest addresses whose float went 1.0->2.0,
2.0->1.0, 0.5->1.0 or 1.0->0.5.
"""

import array
import struct
import subprocess
import sys

PHYS_OFFSET = 0xAF000
START = 0x0
SIZE = 0x3F00000

PAIRS = {
  (0x3F800000, 0x40000000): "1.0 -> 2.0",
  (0x40000000, 0x3F800000): "2.0 -> 1.0",
  (0x3F000000, 0x3F800000): "0.5 -> 1.0",
  (0x3F800000, 0x3F000000): "1.0 -> 0.5",
}


def find_xemu_pid():
  out = subprocess.check_output(["pgrep", "-fa", "^xemu"]).decode()
  return int(out.split()[0])


def snap(ram_base, out_path):
  pid = find_xemu_pid()
  with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem, open(out_path, "wb") as out:
    mem.seek(ram_base + START + PHYS_OFFSET)
    remaining = SIZE
    while remaining:
      chunk = mem.read(min(remaining, 0x100000))
      if len(chunk) == 0:
        raise RuntimeError(f"Short read with {remaining} bytes left")

      out.write(chunk)
      remaining -= len(chunk)


  print(f"Saved {SIZE:#x} bytes to {out_path}")


def load(path):
  words = array.array("I")
  with open(path, "rb") as f:
    words.fromfile(f, SIZE // 4)

  return words


def diff(path_a, path_b):
  a = load(path_a)
  b = load(path_b)
  found = 0
  for i, (x, y) in enumerate(zip(a, b)):
    if x != y:
      label = PAIRS.get((x, y))
      if label is not None:
        print(f"  0x{START + i * 4:08x}: {label}")
        found += 1



  print(f"{found} candidate(s)")


def plausible(v):
  # Small integer, or a float with a sane magnitude.
  if v <= 16:
    return True

  f = struct.unpack("<f", struct.pack("<I", v))[0]
  return f == f and 0.01 <= abs(f) <= 16.0


def diff4(path_off1, path_on1, path_on2, path_off2):
  off1, on1, on2, off2 = (load(p) for p in (path_off1, path_on1, path_on2, path_off2))
  found = 0
  for i, (a, b, c, d) in enumerate(zip(off1, on1, on2, off2)):
    if a == d and b == c and a != b and plausible(a) and plausible(b):
      fa = struct.unpack("<f", struct.pack("<I", a))[0]
      fb = struct.unpack("<f", struct.pack("<I", b))[0]
      print(f"  0x{START + i * 4:08x}: off=0x{a:08x} ({fa:g}) on=0x{b:08x} ({fb:g})")
      found += 1


  print(f"{found} candidate(s)")


if __name__ == "__main__":
  if sys.argv[1] == "diff4":
    diff4(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
  elif sys.argv[1] == "snap":
    snap(int(sys.argv[2], 16), sys.argv[3])
  elif sys.argv[1] == "diff":
    diff(sys.argv[2], sys.argv[3])
  else:
    raise RuntimeError(f"Unknown mode {sys.argv[1]}")

