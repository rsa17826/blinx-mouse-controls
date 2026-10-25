#!/usr/bin/env python3
"""Fast xemu guest-RAM access through /proc/<pid>/mem.

Guest virtual addresses are translated by walking the guest's own x86 page
tables (read straight out of host memory), so any mapped address works and no
virtual->physical offset is assumed. CR3 is read over QMP on every start. The
host RAM base is cached in CACHE_FILE together with the xemu pid and that
process's start time
different process that reused the pid) is it re-derived via the gdbstub.

To force a re-derive:  rm /tmp/xemu_ram_base.json

Requires xemu started with -qmp tcp:HOST:PORT,...

NOTE: writes go straight into host memory while the guest keeps running
guest is NOT halted like it is with gdb_rsp. Data writes are fine. For code
patches, hook bytes are written last, but a write that races guest execution
of those exact bytes is possible.
"""

import json
import os
import re
import socket
import struct
import subprocess
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from gdb_rsp import cmd_continue, connect, read_memory, write_memory # noqa: E402

PAGE = 0x1000
RAM_MIRROR_PHYS = 0xF0000000 # physical addresses >= this are a mirror of RAM at (phys - this)
CACHE_FILE = "/tmp/xemu_ram_base.json"
MIN_RAM_MAPPING = 0x4000000

# Only used when the cache is cold: a random pattern is written here through the
# gdbstub (original bytes restored afterwards, guest halted meanwhile) and then
# searched for in the host RAM mappings. Must be a mapped guest address.
TEST_ADDR = 0x00141FB5
TEST_LEN = 16
SCAN_CHUNK = 0x1000000


def find_xemu_pid():
  out = subprocess.check_output(["pgrep", "-fa", "^xemu"]).decode()
  return int(out.split()[0])


def proc_starttime(pid):
  with open(f"/proc/{pid}/stat") as f:
    stat = f.read()

  # fields after the ")" that closes comm; starttime is field 22 -> index 19
  return int(stat.rsplit(")", 1)[1].split()[19])


def ram_mappings(pid):
  mappings = []
  with open(f"/proc/{pid}/maps") as f:
    for line in f:
      parts = line.split()
      start_s, end_s = parts[0].split("-")
      start, end = int(start_s, 16), int(end_s, 16)
      if end - start >= MIN_RAM_MAPPING and "rw" in parts[1]:
        mappings.append((start, end - start))



  return mappings


def find_in_mapping(fd, start, size, pattern):
  """Yields offsets within the mapping where pattern occurs."""
  pos = 0
  while pos < size:
    n = min(SCAN_CHUNK + len(pattern) - 1, size - pos)
    try:
      data = os.pread(fd, n, start + pos)

    except OSError:
      pos += SCAN_CHUNK
      continue # unreadable range

    i = data.find(pattern)
    while i != -1:
      yield pos + i
      i = data.find(pattern, i + 1)

    pos += SCAN_CHUNK


def derive_ram_base(pid, cr3):
  """Host address of guest physical 0. No virtual->physical offset is assumed: a
  hit only counts if the page-table walk of TEST_ADDR agrees with its offset."""
  mappings = ram_mappings(pid)
  pattern = os.urandom(TEST_LEN)
  fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
  sock = connect()
  last_error = None
  hits = 0
  try:
    original = read_memory(sock, TEST_ADDR, TEST_LEN)
    write_memory(sock, TEST_ADDR, pattern)
    try:
      for start, size in mappings:
        for offset in find_in_mapping(fd, start, size, pattern):
          hits += 1
          try:
            phys = walk_page_tables(lambda p, n: os.pread(fd, n, start + p), cr3, TEST_ADDR)

          except (RuntimeError, OSError) as err:
            last_error = err
            continue # this mapping isn't guest RAM

          if phys == offset:
            return start

          last_error = f"walk gave phys 0x{phys:x}, pattern was at offset 0x{offset:x}"



    finally:
      write_memory(sock, TEST_ADDR, original)


  finally:
    cmd_continue(sock)
    os.close(fd)

  raise RuntimeError(f"Could not locate guest RAM for pid {pid}: {hits} pattern hit(s) in {[(hex(s), hex(z)) for s, z in mappings]}, CR3 0x{cr3:x}, TEST_ADDR 0x{TEST_ADDR:x}, last problem: {last_error}")


def qmp_address(pid):
  with open(f"/proc/{pid}/cmdline", "rb") as f:
    argv = f.read().decode().split("\0")

  if "-qmp" not in argv:
    raise RuntimeError("xemu was not started with -qmp tcp:HOST:PORT,... (needed to read CR3)")

  spec = argv[argv.index("-qmp") + 1]
  host, port = spec.removeprefix("tcp:").split(",")[0].rsplit(":", 1)
  return host, int(port)


def read_cr3(pid):
  host, port = qmp_address(pid)
  with socket.create_connection((host, port), timeout=5) as s:
    f = s.makefile("rw", encoding="utf-8", newline="\n")
    json.loads(f.readline()) # greeting

    def call(command, arguments=None):
      msg = {"execute": command}
      if arguments:
        msg["arguments"] = arguments

      f.write(json.dumps(msg) + "\n")
      f.flush()
      while True:
        reply = json.loads(f.readline())
        if "event" in reply:
          continue

        if "error" in reply:
          raise RuntimeError(f"QMP {command} failed: {reply['error']}")

        return reply["return"]


    call("qmp_capabilities")
    text = call("human-monitor-command", {"command-line": "info registers"})

  m = re.search(r"CR3=([0-9a-fA-F]+)", text)
  if not m:
    raise RuntimeError(f"No CR3 in 'info registers' output:\n{text}")

  return int(m.group(1), 16)


def walk_page_tables(read_phys, cr3, vaddr):
  """x86 32-bit paging (4 KB pages and 4 MB PSE pages). read_phys(phys, n) -> bytes."""
  pde = struct.unpack("<I", read_phys((cr3 & ~0xFFF) + (vaddr >> 22) * 4, 4))[0]
  if not pde & 1:
    raise RuntimeError(f"0x{vaddr:x}: page directory entry not present (0x{pde:x})")

  if pde & 0x80:
    return (pde & 0xFFC00000) | (vaddr & 0x3FFFFF)

  pte = struct.unpack("<I", read_phys((pde & ~0xFFF) + ((vaddr >> 12) & 0x3FF) * 4, 4))[0]
  if not pte & 1:
    raise RuntimeError(f"0x{vaddr:x}: page table entry not present (0x{pte:x})")

  return (pte & 0xFFFFF000) | (vaddr & 0xFFF)


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
  """(pid, ram_base, cr3). The base is cached per xemu process
  QMP every time because it can change if the guest is rebooted."""
  cached = read_cache()
  if cached:
    pid, base = cached
    return pid, base, read_cr3(pid)

  pid = find_xemu_pid()
  print(f"fastmem: no live cached xemu, deriving RAM base for pid {pid}...", file=sys.stderr)
  cr3 = read_cr3(pid)
  base = derive_ram_base(pid, cr3)
  write_cache(pid, base)
  print(f"fastmem: RAM base 0x{base:x} cached in {CACHE_FILE}", file=sys.stderr)
  return pid, base, cr3


class FastMemWriter:
  def __init__(self):
    self.pid, self.ram_base, self.cr3 = load_ram_base()
    self.fd = open(f"/proc/{self.pid}/mem", "r+b", buffering=0)
    self.pages = {} # virtual page -> physical page

  def flush_translations(self):
    self.pages.clear()

  def _read_phys(self, phys, length):
    return os.pread(self.fd.fileno(), length, self.ram_base + phys)

  def _phys_page(self, vpage):
    if vpage not in self.pages:
      phys = walk_page_tables(self._read_phys, self.cr3, vpage) & ~0xFFF
      if phys >= RAM_MIRROR_PHYS:
        phys -= RAM_MIRROR_PHYS

      self.pages[vpage] = phys

    return self.pages[vpage]

  def _chunks(self, addr, length):
    """Yields (host_addr, n) pieces that don't cross a page boundary."""
    while length:
      n = min(length, PAGE - (addr & 0xFFF))
      yield self.ram_base + self._phys_page(addr & ~0xFFF) + (addr & 0xFFF), n
      addr += n
      length -= n


  def read(self, addr, length):
    out = b""
    for host, n in self._chunks(addr, length):
      try:
        data = os.pread(self.fd.fileno(), n, host)

      except OSError as err:
        raise RuntimeError(f"Host read failed for guest 0x{addr:x}: phys 0x{host - self.ram_base:x} is outside the RAM mapping") from err

      if len(data) != n:
        raise RuntimeError(f"Short read at 0x{addr:x}: wanted {n}, got {len(data)}")

      out += data

    return out

  def write(self, addr, data):
    pos = 0
    for host, n in self._chunks(addr, len(data)):
      try:
        written = os.pwrite(self.fd.fileno(), data[pos : pos + n], host)

      except OSError as err:
        raise RuntimeError(f"Host write failed for guest 0x{addr:x}: phys 0x{host - self.ram_base:x} is outside the RAM mapping") from err

      if written != n:
        raise RuntimeError(f"Short write at 0x{addr:x}: wanted {n}, wrote {written}")

      pos += n


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

