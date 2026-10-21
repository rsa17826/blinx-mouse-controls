#!/usr/bin/env python3
"""Minimal QMP client for xemu guest memory inspection.

Usage:
    python3 qmp_bridge.py read <hex_addr> <num_bytes>
    python3 qmp_bridge.py write <hex_addr> <hex_bytes>

Requires xemu launched with: -qmp tcp:localhost:4444,server,nowait
"""

import json
import socket
import sys
import tempfile
import os

HOST = "localhost"
PORT = 4444


def qmp_connect():
  sock = socket.create_connection((HOST, PORT))
  f = sock.makefile("rw")
  greeting = json.loads(f.readline())
  # must send qmp_capabilities to leave negotiation mode
  f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n")
  f.flush()
  resp = json.loads(f.readline())
  if "error" in resp:
    raise RuntimeError(f"QMP capabilities negotiation failed: {resp}")

  return sock, f


def hmc(f, command_line):
  """Send a human-monitor-command and return its output string."""
  f.write(json.dumps({"execute": "human-monitor-command", "arguments": {"command-line": command_line}}) + "\n")
  f.flush()
  resp = json.loads(f.readline())
  if "error" in resp:
    raise RuntimeError(f"Command failed: {resp['error']}")

  return resp.get("return", "")


def read_memory(f, addr, length):
  # memsave dumps guest virtual memory to a host file
  with tempfile.NamedTemporaryFile(delete=False) as tmp:
    tmp_path = tmp.name

  try:
    hmc(f, f"memsave {addr} {length} {tmp_path}")
    with open(tmp_path, "rb") as fh:
      data = fh.read()

    return data

  finally:
    os.unlink(tmp_path)


def write_memory(f, addr, hex_bytes):
  data = bytes.fromhex(hex_bytes)
  # QEMU monitor doesn't have a direct "write file to memory" command by
  # default; use individual byte pokes via 'memset'-style 'w' commands
  # or the pmemsave/loadvm approach. Simplest portable option: use
  # 'x/w' style writes are not available via HMC directly, so we poke
  # byte-by-byte using the monitor's memory write commands.
  for i, byte in enumerate(data):
    hmc(f, f"memsave {addr + i} 1 /dev/null") # placeholder no-op read

  raise NotImplementedError("Direct memory writes via human-monitor-command are limited; see notes below the script for gdbstub-based writing instead.")


if __name__ == "__main__":
  if len(sys.argv) < 4:
    print(__doc__)
    sys.exit(1)

  mode = sys.argv[1]
  addr = int(sys.argv[2], 16)

  sock, f = qmp_connect()

  if mode == "read":
    length = int(sys.argv[3])
    data = read_memory(f, addr, length)
    print(data.hex())
  elif mode == "write":
    write_memory(f, addr, sys.argv[3])
  else:
    print(f"Unknown mode: {mode}")
    sys.exit(1)

