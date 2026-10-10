#!/usr/bin/env python3
"""Iterative memory-address narrowing tool (Cheat-Engine style scan).

Workflow:
    1. Take a baseline snapshot:
         python3 narrow.py snapshot snap1.bin

    2. Do the thing you're tracking (e.g. pick up an item), then:
         python3 narrow.py snapshot snap2.bin

    3. Start the candidate set from the first two snapshots, telling it
       whether the value SHOULD have changed or SHOULD NOT have changed
       between them:
         python3 narrow.py start snap1.bin snap2.bin --changed
         (or --unchanged if you deliberately did nothing between them)

    4. Repeat: take another snapshot, and narrow the existing candidate
       set against the previous snapshot:
         python3 narrow.py snapshot snap3.bin
         python3 narrow.py narrow snap2.bin snap3.bin --changed
         python3 narrow.py snapshot snap4.bin
         python3 narrow.py narrow snap3.bin snap4.bin --unchanged
         ... repeat, alternating "did the thing" / "did nothing" rounds,

       until candidates.json is down to a small, manageable list.

    5. Check progress any time:
         python3 narrow.py show


Candidates are stored in candidates.json in the current directory.
Only the specific byte offsets in the candidate set are ever read back
out of the (large) snapshot files, so this stays fast even though the
snapshots themselves are full 128MB RAM dumps.
"""

import json
import os
import socket
import sys

import numpy as np

HOST = "localhost"
PORT = 4444
RAM_SIZE = 128 * 1024 * 1024
CANDIDATES_FILE = "candidates.npy"


def qmp_connect():
  sock = socket.create_connection((HOST, PORT))
  f = sock.makefile("rw")
  json.loads(f.readline())
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


def cmd_snapshot(out_path, base=0, size=None):
  if size is None:
    size = RAM_SIZE

  sock, f = qmp_connect()
  hmc(f, f"pmemsave 0x{base:x} {size} {out_path}")
  print(f"Wrote {size} bytes of guest RAM (base 0x{base:08x}) to {out_path}")


def read_byte(path, addr):
  with open(path, "rb") as fh:
    fh.seek(addr)
    b = fh.read(1)
    if len(b) != 1:
      raise ValueError(f"Address 0x{addr:08x} out of range for {path}")

    return b[0]


def full_diff_addresses(path_a, path_b):
  """Only used once, for the initial 'start' step - uses numpy for a
  vectorized comparison instead of a per-byte python loop."""
  a = np.fromfile(path_a, dtype=np.uint8)
  b = np.fromfile(path_b, dtype=np.uint8)
  if len(a) != len(b):
    raise ValueError(f"Snapshot sizes differ: {len(a)} vs {len(b)}")

  changed = np.flatnonzero(a != b)
  return changed, len(a)


def save_candidates(addrs):
  np.asarray(addrs, dtype=np.int64).tofile(CANDIDATES_FILE)


def load_candidates():
  if not os.path.exists(CANDIDATES_FILE):
    raise FileNotFoundError(f"{CANDIDATES_FILE} not found - run 'start' first")

  return np.fromfile(CANDIDATES_FILE, dtype=np.int64)


def cmd_start(path_a, path_b, mode):
  changed, total = full_diff_addresses(path_a, path_b)
  if mode == "changed":
    candidates = changed
  elif mode == "unchanged":
    changed_set = set(changed)
    candidates = [i for i in range(total) if i not in changed_set]
  else:
    raise ValueError("mode must be 'changed' or 'unchanged'")

  save_candidates(candidates)
  print(f"Initial candidate set: {len(candidates)} addresses (out of {total} total bytes)")


def cmd_narrow(path_a, path_b, mode):
  candidates = load_candidates()
  a = np.fromfile(path_a, dtype=np.uint8)
  b = np.fromfile(path_b, dtype=np.uint8)
  va = a[candidates]
  vb = b[candidates]
  if mode == "changed":
    keep_mask = va != vb
  elif mode == "unchanged":
    keep_mask = va == vb
  else:
    raise ValueError("mode must be 'changed' or 'unchanged'")

  kept = candidates[keep_mask]
  save_candidates(kept)
  print(f"Narrowed from {len(candidates)} to {len(kept)} candidates")


def cmd_values(snapshot_path):
  candidates = load_candidates()
  data = np.fromfile(snapshot_path, dtype=np.uint8)
  values = data[candidates]
  order = np.argsort(candidates)
  sorted_addrs = candidates[order]
  sorted_vals = values[order]

  print(f"{len(candidates)} candidate address(es), values from {snapshot_path}:")
  prev_addr = None
  for addr, val in zip(sorted_addrs, sorted_vals):
    addr = int(addr)
    gap_marker = ""
    if prev_addr is not None and addr - prev_addr > 64:
      gap_marker = "  -- gap --"

    print(f"  0x{addr:08x}: {val:3d} (0x{val:02x}){gap_marker}")
    prev_addr = addr


def cmd_show():
  candidates = load_candidates()
  print(f"{len(candidates)} candidate address(es):")
  for addr in candidates[:100]:
    print(f"  0x{int(addr):08x}")

  if len(candidates) > 100:
    print(f"  ... and {len(candidates) - 100} more (truncated)")


if __name__ == "__main__":
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  mode = sys.argv[1]

  if mode == "snapshot":
    out_path = sys.argv[2]
    if len(sys.argv) >= 5:
      base = int(sys.argv[3], 16)
      size = int(sys.argv[4], 16)
      cmd_snapshot(out_path, base=base, size=size)
    else:
      cmd_snapshot(out_path)

  elif mode == "start":
    flag = sys.argv[4] if len(sys.argv) > 4 else "--changed"
    cmd_start(sys.argv[2], sys.argv[3], flag.lstrip("-"))
  elif mode == "narrow":
    flag = sys.argv[4] if len(sys.argv) > 4 else "--changed"
    cmd_narrow(sys.argv[2], sys.argv[3], flag.lstrip("-"))
  elif mode == "show":
    cmd_show()
  elif mode == "values":
    cmd_values(sys.argv[2])
  else:
    print(f"Unknown mode: {mode}")
    sys.exit(1)

