#!/usr/bin/env python3
"""Re-derive xemu's guest-RAM host base address after restarting xemu."""

import struct
import subprocess
import sys

sys.path.insert(0, ".")
from gdb_rsp import cmd_continue, connect, read_memory, write_memory # noqa: E402

PHYS_OFFSET = 0xAF000
# CONFIRMED RAM_HOST_BASE = 0x702eabc00000


def find_xemu_pid():
  out = subprocess.check_output(["pgrep", "-fa", "^xemu"]).decode()
  print(out, file=sys.stderr)
  return int(out.split()[0])


def find_ram_mappings(pid):
  candidates = []
  with open(f"/proc/{pid}/maps") as f:
    for line in f:
      parts = line.split()
      if len(parts) < 2:
        continue

      start_s, end_s = parts[0].split("-")
      size = int(end_s, 16) - int(start_s, 16)
      perms = parts[1]

      # Include any private/shared writable mapping >= 64MB
      if size >= 0x4000000 and "rw" in perms:
        candidates.append((int(start_s, 16), size))



  return candidates


def main():
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  test_addr = int(sys.argv[1], 16)
  pid = find_xemu_pid()
  print(f"xemu PID: {pid}", file=sys.stderr)

  candidates = find_ram_mappings(pid)
  print(
    f"Found {len(candidates)} candidate RAM mapping(s): {[hex(c[0]) for c in candidates]}",
    file=sys.stderr,
  )

  # Write test pattern via GDB
  distinctive = struct.pack("<f", 2.71828)
  sock = connect()
  write_memory(sock, test_addr, distinctive)
  gdb_value = read_memory(sock, test_addr, 4)
  cmd_continue(sock)

  phys = test_addr + PHYS_OFFSET

  # Method 1: Try direct calculation using PHYS_OFFSET
  with open(f"/proc/{pid}/mem", "rb") as f:
    for base, size in candidates:
      host_addr = base + phys
      try:
        f.seek(host_addr)
        val = f.read(4)
        if val == gdb_value:
          print(f"\nCONFIRMED RAM_HOST_BASE = 0x{base:x}", file=sys.stderr)
          print(f"0x{base:x}", file=sys.stdout)
          return


      except OSError:
        continue



  # Method 2: Fallback scan across candidate region if PHYS_OFFSET is wrong
  print(
    "\nDirect offset match failed. Scanning candidate regions...",
    file=sys.stderr,
  )
  with open(f"/proc/{pid}/mem", "rb") as f:
    for base, size in candidates:
      f.seek(base)
      data = f.read(size)
      found_offset = data.find(gdb_value)
      if found_offset != -1:
        derived_phys_offset = found_offset - test_addr
        print(
          f"\nFOUND via memory scan! RAM_HOST_BASE = 0x{base:x}",
          file=sys.stderr,
        )
        print(
          f"Detected actual physical offset: 0x{derived_phys_offset:x} (configured PHYS_OFFSET was 0x{PHYS_OFFSET:x})",
          file=sys.stderr,
        )
        print(f"0x{base:x}", file=sys.stdout)
        return



  print(
    "\nNo match found. Ensure GDB memory write succeeded and test_addr is writable.",
    file=sys.stderr,
  )


if __name__ == "__main__":
  main()
