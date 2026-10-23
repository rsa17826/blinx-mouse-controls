#!/usr/bin/env python3
"""Force the player's stick-vs-heading angle (sVar10, in di) to 0.

Hook: 0xd53cc, 10 bytes:
    xor edi,edi
The cave re-executes them, then zeroes edi when esi is the player object
(the pointer stored at 0x4eaa04). Other actors are untouched.
Result: sector (player+0x1b) is always 0, so no side/back flips and no
turn-around sub-states (player+0x20 = 5/6).

Usage:
    python3 install_zero_stick_angle.py <hex_cave_addr>

The cave must be 32 zero bytes. Load a savestate with original bytes first.
"""
import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../lib')))
from gdb_rsp import connect, read_memory, write_memory, cmd_continue
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

HOOK_ADDR = 0x000D53CC
HOOK_LEN = 10
RETURN_ADDR = 0x000D53D6
ORIGINAL = bytes.fromhex("33ff668bf88a46202bfb")
PLAYER_OBJ_PTR = 0x004EAA04
CAVE_SIZE = 32


def asm(ks, code, address):
  encoding, _ = ks.asm(code, address)
  return bytes(encoding)


def verified_write(sock, addr, data, label):
  write_memory(sock, addr, data)
  readback = read_memory(sock, addr, len(data))
  if readback != data:
    raise RuntimeError(f"Write verification FAILED for {label}: wrote {data.hex()}, read {readback.hex()}")
  print(f"  verified: {label} at 0x{addr:08x}")


def main():
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  cave = int(sys.argv[1], 16)
  ks = Ks(KS_ARCH_X86, KS_MODE_32)
  tail = asm(
    ks,
    f"""
        cmp esi, dword ptr [0x{PLAYER_OBJ_PTR:x}]
        jne done
        xor edi, edi
    done:
        jmp 0x{RETURN_ADDR:x}
    """,
    cave + HOOK_LEN,
  )
  stub = ORIGINAL + tail
  if len(stub) > CAVE_SIZE:
    raise RuntimeError(f"Stub too large: {len(stub)} bytes")
  hook = asm(ks, f"jmp 0x{cave:x}", HOOK_ADDR)
  hook += b"\x90" * (HOOK_LEN - len(hook))

  sock = connect()
  try:
    current = read_memory(sock, HOOK_ADDR, HOOK_LEN)
    if current != ORIGINAL:
      raise RuntimeError(f"Unexpected bytes at 0x{HOOK_ADDR:x}: {current.hex()} (already patched? load the savestate)")
    if read_memory(sock, cave, CAVE_SIZE) != bytes(CAVE_SIZE):
      raise RuntimeError(f"Cave at 0x{cave:x} is not {CAVE_SIZE} zero bytes")
    verified_write(sock, cave, stub, "stub")
    verified_write(sock, HOOK_ADDR, hook, "hook")
  finally:
    cmd_continue(sock)
  print("Stick angle zeroing installed.")


if __name__ == "__main__":
  main()
