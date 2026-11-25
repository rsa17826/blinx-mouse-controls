#!/usr/bin/env python3
"""Find per-frame counters and timers in static memory during a screen.

Usage:
    python3 counter_scan.py <delay_s> <interval_s>

Waits <delay_s>, then takes three snapshots of the static data area
(0x1d8000..0xc00000, virtual) <interval_s> apart. A word is a candidate when it
changes by a steady step between the snapshots, either as an integer (frame
counter) or as a float (timer). Start the load or save, then run this so all
three snapshots fall inside the screen (a 4 s screen allows delay 0.5, interval 0.8).
"""
import array
import os
import struct
import sys
import time

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from fastmem import FastMemWriter  # noqa: E402

LO = 0x1D8000
HI = 0xC00000
PAGE = 0x1000
MAX_PRINT = 80


def signed(x):
  return x - (1 << 32) if x & 0x80000000 else x


def snapshot(mem):
  words = array.array("I")
  bad = 0
  for addr in range(LO, HI, PAGE):
    try:
      data = mem.read(addr, PAGE)
    except RuntimeError:
      bad += 1
      data = bytes(PAGE)
    words.frombytes(data)
  return words, bad


def main():
  delay = float(sys.argv[1])
  interval = float(sys.argv[2])
  mem = FastMemWriter()
  try:
    time.sleep(delay)
    snaps = []
    bad = 0
    for i in range(3):
      started = time.monotonic()
      words, b = snapshot(mem)
      bad += b
      snaps.append(words)
      if i < 2:
        time.sleep(max(0.0, interval - (time.monotonic() - started)))
  finally:
    mem.close()

  print(f"unreadable pages across snapshots: {bad}")
  a, b, c = snaps
  ints = []
  floats = []
  for i, (wa, wb, wc) in enumerate(zip(a, b, c)):
    if wa == wb == wc:
      continue
    d1 = signed((wb - wa) & 0xFFFFFFFF)
    d2 = signed((wc - wb) & 0xFFFFFFFF)
    addr = LO + i * 4
    if d1 != 0 and d1 * d2 > 0 and abs(d1 - d2) <= max(2, abs(d1) // 10) and abs(d1) <= 100000:
      ints.append((addr, wa, wb, wc, d1, d2))
      continue
    fa, fb, fc = struct.unpack("<3f", struct.pack("<3I", wa, wb, wc))
    f1 = fb - fa
    f2 = fc - fb
    if f1 == f1 and f2 == f2 and abs(f1) > 1e-4 and abs(f1) < 1e6 and f1 * f2 > 0 and abs(f1 - f2) <= abs(f1) * 0.15:
      floats.append((addr, fa, fb, fc, f1, f2))

  print(f"integer counters: {len(ints)}")
  for addr, wa, wb, wc, d1, d2 in ints[:MAX_PRINT]:
    print(f"  0x{addr:08x}: {wa} -> {wb} -> {wc}  (steps {d1:+d}, {d2:+d})")
  print(f"float timers: {len(floats)}")
  for addr, fa, fb, fc, f1, f2 in floats[:MAX_PRINT]:
    print(f"  0x{addr:08x}: {fa:.3f} -> {fb:.3f} -> {fc:.3f}  (steps {f1:+.3f}, {f2:+.3f})")
  if len(ints) > MAX_PRINT or len(floats) > MAX_PRINT:
    print(f"(output truncated to {MAX_PRINT} per list)")


if __name__ == "__main__":
  main()
