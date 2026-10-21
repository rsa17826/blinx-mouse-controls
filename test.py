#!/usr/bin/env python3
"""stride_diff.py <resultsA.txt> <resultsB.txt>
Prints stride_scan.py hits whose (stride, phys) appear in both files."""

import re
import sys

HDR = re.compile(r"^stride (0x[0-9a-f]+): phys (0x[0-9a-f]+)")


def parse(path):
  hits = {}
  cur = None
  with open(path) as f:
    for line in f:
      m = HDR.match(line)
      if m:
        cur = (m.group(1), m.group(2))
        hits[cur] = []
      elif cur is not None and line.startswith("    "):
        hits[cur].append(line.rstrip())

  if not hits:
    raise RuntimeError(f"No hits found in {path} - is it stride_scan.py output?")

  return hits


a = parse(sys.argv[1])
b = parse(sys.argv[2])
both = sorted(set(a) & set(b), key=lambda k: int(k[1], 16))
print(f"{len(a)} hits in A, {len(b)} in B, {len(both)} in both")

for key in both:
  stride, phys = key
  print(f"stride {stride}: phys {phys}")
  for line in a[key]:
    print(f"  A{line}")

  for line in b[key]:
    print(f"  B{line}")