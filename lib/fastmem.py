#!/usr/bin/env python3
"""Fast xemu guest-RAM access through /proc/<pid>/mem.

The host address of guest RAM (RAM_HOST_BASE) is cached in CACHE_FILE together
with the xemu pid and that process's start time. FastMemWriter() reads the
cache; only when the cached pid no longer exists (or is a different process
that reused the pid) does it re-derive the base via the gdbstub, which is the
slow part, and rewrite the cache.

To force a re-derive:  rm /tmp/xemu_ram_base.json

NOTE: writes go straight into host memory while the guest keeps running; the
guest is NOT halted like it is with gdb_rsp. Data writes are fine. For code
patches, hook bytes are written last, but a write that races guest execution
of those exact bytes is possible.
"""

import json
import os
import struct
import subprocess
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from gdb_rsp import cmd_continue, connect, read_memory, write_memory  # noqa: E402

PHYS_OFFSET = 0xAF000  # guest virtual -> physical (low game addresses)
CONTIG_ALIAS = 0xF0000000  # write-combined alias of physical RAM: phys = addr - this
KERNEL_BASE = 0x80000000  # addresses in [KERNEL_BASE, CONTIG_ALIAS) are not mapped here
CACHE_FILE = "/tmp/xemu_ram_base.json"
MIN_RAM_MAPPING = 0x4000000

# Only used when the cache is cold. Must be an address where addr + PHYS_OFFSET
# is valid (0x141fb5 is what find_ram_base.py confirmed on this setup). The
# original bytes are saved and restored while the guest is halted by the gdbstub.
TEST_ADDR = 0x00141FB5
TEST_LEN = 16


def find_xemu_pid():
  out = subprocess.check_output(["pgrep", "-fa", "^xemu"]).decode()
  return int(out.split()[0])


def proc_starttime(pid):
  with open(f"/proc/{pid}/stat") as f:
    stat = f.read()

  # fields after the ")" that closes comm; starttime is field 22 -> index 19
  return int(stat.rsplit(")", 1)[1].split()[19])


def ram_mappings(pid):
  candidates = []
  with open(f"/proc/{pid}/maps") as f:
    for line in f:
      parts = line.split()
      start_s, end_s = parts[0].split("-")
      start, end = int(start_s, 16), int(end_s, 16)
      if end - start >= MIN_RAM_MAPPING and "rw" in parts[1]:
        candidates.append(start)

  return candidates


def derive_ram_base(pid):
  candidates = ram_mappings(pid)
  pattern = os.urandom(TEST_LEN)
  fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
  sock = connect()
  try:
    original = read_memory(sock, TEST_ADDR, TEST_LEN)
    write_memory(sock, TEST_ADDR, pattern)
    try:
      for base in candidates:
        try:
          if os.pread(fd, TEST_LEN, base + TEST_ADDR + PHYS_OFFSET) == pattern:
            return base

        except OSError:
          continue # candidate mapping doesn't reach this address

    finally:
      write_memory(sock, TEST_ADDR, original)

  finally:
    cmd_continue(sock)
    os.close(fd)

  raise RuntimeError(f"No RAM mapping of pid {pid} matched the gdbstub test write at 0x{TEST_ADDR:x} (candidates: {[hex(c) for c in candidates]}). Is PHYS_OFFSET 0x{PHYS_OFFSET:x} still right?")


def read_cache():
  """Returns (pid, base) if the cached xemu process is still the same process, else None."""
  if not os.path.exists(CACHE_FILE):
    return None

  with open(CACHE_FILE) as f:
    cached = json.load(f)

  pid = cached["pid"]
  if not os.path.exists(f"/proc/{pid}"):
    return None

  if proc_starttime(pid) != cached["starttime"]:
    return None # pid was reused by a different process

  return pid, cached["base"]


def write_cache(pid, base):
  tmp = f"{CACHE_FILE}.{os.getpid()}.tmp"
  with open(tmp, "w") as f:
    json.dump({"pid": pid, "starttime": proc_starttime(pid), "base": base}, f)

  os.replace(tmp, CACHE_FILE)


def load_ram_base():
  cached = read_cache()
  if cached:
    return cached

  pid = find_xemu_pid()
  print(f"fastmem: no live cached xemu, deriving RAM base for pid {pid} via gdbstub...", file=sys.stderr)
  base = derive_ram_base(pid)
  write_cache(pid, base)
  print(f"fastmem: RAM base 0x{base:x} cached in {CACHE_FILE}", file=sys.stderr)
  return pid, base


class FastMemWriter:
  def __init__(self):
    self.pid, self.ram_base = load_ram_base()
    self.fd = open(f"/proc/{self.pid}/mem", "r+b", buffering=0)

  def host_addr(self, addr):
    if addr >= CONTIG_ALIAS:
      return self.ram_base + (addr - CONTIG_ALIAS)

    if addr >= KERNEL_BASE:
      raise ValueError(f"0x{addr:x} is in an unsupported address region")

    return self.ram_base + addr + PHYS_OFFSET

  def read(self, addr, length):
    data = os.pread(self.fd.fileno(), length, self.host_addr(addr))
    if len(data) != length:
      raise RuntimeError(f"Short read at 0x{addr:x}: wanted {length}, got {len(data)}")

    return data

  def write(self, addr, data):
    written = os.pwrite(self.fd.fileno(), data, self.host_addr(addr))
    if written != len(data):
      raise RuntimeError(f"Short write at 0x{addr:x}: wanted {len(data)}, wrote {written}")

  def write_verified(self, addr, data, label):
    self.write(addr, data)
    readback = self.read(addr, len(data))
    if readback != data:
      raise RuntimeError(f"Write verification FAILED for {label} at 0x{addr:x}: wrote {data.hex()}, read back {readback.hex()}.")

    print(f"  verified write OK: {label} at 0x{addr:08x} ({len(data)} bytes)")

  def write_float(self, addr, value):
    self.write(addr, struct.pack("<f", value))

  def read_float(self, addr):
    return struct.unpack("<f", self.read(addr, 4))[0]

  def close(self):
    self.fd.close()
