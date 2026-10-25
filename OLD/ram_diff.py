#!/usr/bin/env python3
"""RAM snapshot-diff tool via xemu's QMP interface.

Workflow:
    1. Launch xemu with: -qmp tcp:localhost:4444,server,nowait
    2. Get to a stable point in-game (before picking up an item).
    3. Run: python3 ram_diff.py snapshot before.bin
    4. Pick up the item / trigger the change in-game.
    5. Run: python3 ram_diff.py snapshot after.bin
    6. Run: python3 ram_diff.py diff before.bin after.bin
       -> prints addresses (and old/new byte values) that changed.

Notes:
    - The Xbox has 64MB or 128MB of RAM depending on config; this dumps
      the full guest physical RAM region starting at 0x0.
    - Repeat the before/after cycle multiple times with DIFFERENT items
      to narrow down which changed address is specific to the item you
      care about (lots of addresses change every frame from unrelated
      game state - timers, animation counters, etc).

"""

import json
import socket
import sys

import numpy as np

HOST = "localhost"
PORT = 4444
RAM_SIZE = 128 * 1024 * 1024 # matches your -m 128 launch arg


def qmp_connect():
  sock = socket.create_connection((HOST, PORT))
  f = sock.makefile("rw")
  json.loads(f.readline()) # greeting
  f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n")
  f.flush()
  resp = json.loads(f.readline())
  if "error" in resp:
    raise RuntimeError(f"QMP capabilities negotiation failed: {resp}")

  return sock, f


def hmc(f, command_line):
  f.write(json.dumps({"execute": "human-monitor-command", "arguments": {"command-line": command_line}}) + "\n")
  f.flush()
  resp = json.loads(f.readline())
  if "error" in resp:
    raise RuntimeError(f"Command failed: {resp['error']}")

  return resp.get("return", "")


def snapshot(out_path, base=0, size=None):
  if size is None:
    size = RAM_SIZE

  sock, f = qmp_connect()
  hmc(f, f"pmemsave 0x{base:x} {size} {out_path}")
  print(f"Wrote {size} bytes of guest RAM (base 0x{base:08x}) to {out_path}")


def diff(before_path, after_path, base=0):
  before = np.fromfile(before_path, dtype=np.uint8)
  after = np.fromfile(after_path, dtype=np.uint8)

  if len(before) != len(after):
    raise ValueError(f"Snapshot sizes differ: {len(before)} vs {len(after)} - were both dumps taken with the same range?")

  changed_idx = np.flatnonzero(before != after)
  print(f"{len(changed_idx)} byte(s) changed out of {len(before)} (physical addresses, base 0x{base:08x})")
  for i in changed_idx[:200]:
    i = int(i)
    print(f"0x{i + base:08x}: {before[i]:#04x} -> {after[i]:#04x}")


  if len(changed_idx) > 200:
    print(f"... and {len(changed_idx) - 200} more (truncated)")


if __name__ == "__main__":
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  mode = sys.argv[1]
  if mode == "snapshot":
    out_path = sys.argv[2]
    if len(sys.argv) >= 5:
      snapshot(out_path, base=int(sys.argv[3], 16), size=int(sys.argv[4], 16))
    else:
      snapshot(out_path)

  elif mode == "diff":
    before_path, after_path = sys.argv[2], sys.argv[3]
    base = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0
    diff(before_path, after_path, base=base)
  else:
    print(f"Unknown mode: {mode}")
    sys.exit(1)

