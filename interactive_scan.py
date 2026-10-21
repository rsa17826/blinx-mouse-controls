#!/usr/bin/env python3
"""Interactive single-keypress memory address narrowing tool, with
session persistence so a crash (yours or xemu's) doesn't lose progress.

Keys:
    i - init/restart: take a fresh baseline snapshot, reset candidates
    c - CHANGED: take a new snapshot, keep only candidates whose value
        changed since the last snapshot
    n - NOT changed: take a new snapshot, keep only candidates whose
        value stayed the same since the last snapshot
    e - VALUE EQUALS: take a new snapshot, then type a value (decimal
        or 0x hex) - keeps only candidates currently equal to it
    g - VALUE GREATER THAN: same, but keeps candidates > typed value
    l - VALUE LESS THAN: same, but keeps candidates < typed value
    v - show current candidate values (address + byte value)
    s - show current candidate count
    q - quit

State (candidates + which snapshot is the current baseline) is saved
to disk after every successful round. If xemu crashes or you Ctrl-C,
just fix xemu and rerun this script - it picks up where you left off.

Snapshots are written to the current directory (proven reliable in
your setup) rather than /dev/shm, since /dev/shm writes were silently
failing. Requires xemu running with:
    -qmp tcp:localhost:4444,server,nowait

"""

import json
import os
import socket
import sys
import termios
import time
import tty

import numpy as np

HOST = "localhost"
PORT = 4444
RAM_SIZE = 128 * 1024 * 1024
SNAP_DIR = "."
SESSION_FILE = "session_state.json"
CANDIDATES_FILE = "session_candidates.npy"

# Range to scan. Defaults to full RAM, but can be narrowed via CLI args
# (see main()) to dramatically speed up snapshots and avoid long BQL
# stalls that can hang xemu / time out QMP.
SCAN_BASE = 0
SCAN_SIZE = RAM_SIZE


def qmp_connect(retries=3, delay=1.0):
  last_err = None
  for attempt in range(retries):
    try:
      sock = socket.create_connection((HOST, PORT), timeout=5)
      f = sock.makefile("rw")
      json.loads(f.readline())
      f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n")
      f.flush()
      resp = json.loads(f.readline())
      if "error" in resp:
        raise RuntimeError(f"QMP capabilities negotiation failed: {resp}")

      return sock, f

    except (ConnectionRefusedError, ConnectionResetError, OSError) as e:
      last_err = e
      print(f"  QMP connect attempt {attempt + 1}/{retries} failed: {e}")
      time.sleep(delay)


  raise RuntimeError(f"Could not connect to QMP after {retries} attempts - is xemu running? Last error: {last_err}")


def hmc(f, command_line):
  f.write(json.dumps({"execute": "human-monitor-command", "arguments": {"command-line": command_line}}) + "\n")
  f.flush()
  resp = json.loads(f.readline())
  if "error" in resp:
    raise RuntimeError(f"Command failed: {resp['error']}")

  return resp.get("return", "")


def take_snapshot(path):
  """Take a snapshot of the configured [SCAN_BASE, SCAN_BASE+SCAN_SIZE)
  range and verify the file actually landed with the right size
  before trusting it - no silent failures."""
  sock, f = qmp_connect()
  hmc(f, f"pmemsave 0x{SCAN_BASE:x} {SCAN_SIZE} {path}")
  if not os.path.exists(path):
    raise RuntimeError(f"pmemsave reported success but {path} was not created - check xemu's working directory / write permissions")

  size = os.path.getsize(path)
  if size != SCAN_SIZE:
    raise RuntimeError(f"Snapshot {path} has wrong size: {size} bytes, expected {SCAN_SIZE} - snapshot may be incomplete")


def get_key():
  fd = sys.stdin.fileno()
  old_settings = termios.tcgetattr(fd)
  try:
    tty.setraw(fd)
    ch = sys.stdin.read(1)

  finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

  return ch


class State:
  def __init__(self):
    self.candidates = None # numpy array of addresses, or None
    self.last_snapshot_path = None
    self.round_num = 0
    self.scan_base = SCAN_BASE
    self.scan_size = SCAN_SIZE

  def save(self):
    with open(SESSION_FILE, "w") as f:
      json.dump(
        {
          "last_snapshot_path": self.last_snapshot_path,
          "round_num": self.round_num,
          "has_candidates": self.candidates is not None,
          "scan_base": self.scan_base,
          "scan_size": self.scan_size,
        },
        f,
      )

    if self.candidates is not None:
      self.candidates.tofile(CANDIDATES_FILE)


  def load(self):
    if not os.path.exists(SESSION_FILE):
      return False

    with open(SESSION_FILE) as f:
      data = json.load(f)

    self.last_snapshot_path = data["last_snapshot_path"]
    self.round_num = data["round_num"]
    self.scan_base = data.get("scan_base", 0)
    self.scan_size = data.get("scan_size", RAM_SIZE)
    if data["has_candidates"] and os.path.exists(CANDIDATES_FILE):
      self.candidates = np.fromfile(CANDIDATES_FILE, dtype=np.int64)
    else:
      self.candidates = None

    # Sanity check the referenced snapshot still exists
    if self.last_snapshot_path and not os.path.exists(self.last_snapshot_path):
      print(f"Warning: previous snapshot {self.last_snapshot_path} is missing - you'll need to press 'i' to reset.")
      self.last_snapshot_path = None

    return True


def do_init(state: State):
  state.round_num += 1
  path = f"{SNAP_DIR}/interactive_{state.round_num}.bin"
  print("Taking baseline snapshot...")
  try:
    take_snapshot(path)

  except Exception as e:
    print(f"FAILED: {e}")
    state.round_num -= 1
    return

  state.last_snapshot_path = path
  state.candidates = None
  state.save()
  print(f"Baseline set ({path}). Candidates reset.")


def do_round(state: State, mode: str):
  if state.last_snapshot_path is None:
    print("No baseline yet - press 'i' first.")
    return

  round_num = state.round_num + 1
  new_path = f"{SNAP_DIR}/interactive_{round_num}.bin"
  print("Taking snapshot...")
  try:
    take_snapshot(new_path)

  except Exception as e:
    print(f"FAILED: {e} - state unchanged, safe to retry.")
    return

  old = np.fromfile(state.last_snapshot_path, dtype=np.uint8)
  new = np.fromfile(new_path, dtype=np.uint8)
  if len(old) != len(new):
    print(f"FAILED: snapshot sizes differ ({len(old)} vs {len(new)}) - state unchanged, safe to retry.")
    return

  if state.candidates is None:
    diff_mask = old != new
    if mode == "changed":
      new_candidates = np.flatnonzero(diff_mask)
    else:
      new_candidates = np.flatnonzero(~diff_mask)

  else:
    va = old[state.candidates]
    vb = new[state.candidates]
    if mode == "changed":
      keep_mask = va != vb
    else:
      keep_mask = va == vb

    new_candidates = state.candidates[keep_mask]

  old_path = state.last_snapshot_path
  state.candidates = new_candidates
  state.last_snapshot_path = new_path
  state.round_num = round_num
  state.save()

  if os.path.exists(old_path):
    os.remove(old_path)

  print(f"[{mode}] Candidates: {len(state.candidates)}")


def prompt_value(label):
  """Prompt for a typed numeric value (decimal, or hex with 0x
  prefix). Terminal is already in normal/cooked mode here since
  get_key() only sets raw mode for the duration of a single read."""
  raw = input(f"{label} (decimal or 0x hex): ").strip()
  if raw.lower().startswith("0x"):
    return int(raw, 16)

  return int(raw)


def do_filter_value(state: State, comparator: str):
  """Take a fresh snapshot and narrow candidates to those whose
  current byte value satisfies the given comparison against a
  user-typed value. comparator is one of 'eq', 'gt', 'lt'."""
  if state.candidates is None:
    print("No candidates yet - press 'i' first.")
    return

  try:
    target = prompt_value("Value")

  except ValueError as e:
    print(f"Invalid value: {e}")
    return

  if not (0 <= target <= 255):
    print(f"Value {target} is out of byte range (0-255).")
    return

  round_num = state.round_num + 1
  new_path = f"{SNAP_DIR}/interactive_{round_num}.bin"
  print("Taking snapshot...")
  try:
    take_snapshot(new_path)

  except Exception as e:
    print(f"FAILED: {e} - state unchanged, safe to retry.")
    return

  new = np.fromfile(new_path, dtype=np.uint8)
  vals = new[state.candidates]

  if comparator == "eq":
    keep_mask = vals == target
  elif comparator == "gt":
    keep_mask = vals > target
  elif comparator == "lt":
    keep_mask = vals < target
  else:
    raise ValueError(f"Unknown comparator: {comparator}")

  old_path = state.last_snapshot_path
  new_candidates = state.candidates[keep_mask]

  state.candidates = new_candidates
  state.last_snapshot_path = new_path
  state.round_num = round_num
  state.save()

  if old_path and os.path.exists(old_path):
    os.remove(old_path)

  symbol = {"eq": "==", "gt": ">", "lt": "<"}[comparator]
  print(f"[value {symbol} {target}] Candidates: {len(state.candidates)}")


def do_show_count(state: State):
  if state.candidates is None:
    print("No candidates yet.")
  else:
    print(f"{len(state.candidates)} candidate address(es)")


def do_show_values(state: State):
  if state.candidates is None:
    print("No candidates yet.")
    return

  if state.last_snapshot_path is None or not os.path.exists(state.last_snapshot_path):
    print("No valid snapshot on disk.")
    return

  data = np.fromfile(state.last_snapshot_path, dtype=np.uint8)
  values = data[state.candidates]
  order = np.argsort(state.candidates)
  sorted_addrs = state.candidates[order]
  sorted_vals = values[order]
  print(f"{len(state.candidates)} candidate(s) (physical addresses, scan range base 0x{SCAN_BASE:08x}):")
  prev_addr = None
  for addr, val in zip(sorted_addrs, sorted_vals):
    physical_addr = int(addr) + SCAN_BASE
    gap = "  -- gap --" if prev_addr is not None and physical_addr - prev_addr > 64 else ""
    print(f"  0x{physical_addr:08x}: {val:3d} (0x{val:02x}){gap}")
    prev_addr = physical_addr


def main():
  global SCAN_BASE, SCAN_SIZE

  if len(sys.argv) >= 3:
    SCAN_BASE = int(sys.argv[1], 16)
    SCAN_SIZE = int(sys.argv[2], 16)
  elif len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
    print(__doc__)
    print("\nOptional: python3 interactive_scan.py <hex_base> <hex_size>")
    print("  e.g. python3 interactive_scan.py a00000 200000")
    print("  (scans 0x00a00000 - 0x00c00000 instead of full RAM)")
    sys.exit(0)

  state = State()
  print(__doc__)
  print(f"\nScan range: 0x{SCAN_BASE:08x} - 0x{SCAN_BASE + SCAN_SIZE:08x} ({SCAN_SIZE} bytes)")
  if state.load():
    if state.scan_base != SCAN_BASE or state.scan_size != SCAN_SIZE:
      print(f"WARNING: saved session used a different range (0x{state.scan_base:08x}, size 0x{state.scan_size:08x}) - press 'i' to reset for the new range, or rerun with matching args to resume properly.")

    print(f"Resumed session: round {state.round_num}, {'candidates loaded' if state.candidates is not None else 'no candidates yet'}, baseline={state.last_snapshot_path}")
  else:
    print("No previous session found - press 'i' to start.")

  print("\nReady. Press a key:")
  while True:
    key = get_key()
    if key == "i":
      do_init(state)
    elif key == "c":
      do_round(state, "changed")
    elif key == "n":
      do_round(state, "unchanged")
    elif key == "e":
      do_filter_value(state, "eq")
    elif key == "g":
      do_filter_value(state, "gt")
    elif key == "l":
      do_filter_value(state, "lt")
    elif key == "v":
      do_show_values(state)
    elif key == "s":
      do_show_count(state)
    elif key == "q":
      print("Quitting. Session saved - rerun this script to resume.")
      break
    else:
      print(f"Unknown key: {key!r} (use i/c/n/e/g/l/v/s/q)")



if __name__ == "__main__":
  main()
