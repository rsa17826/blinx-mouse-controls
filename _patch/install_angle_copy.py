#!/usr/bin/env python3
"""Redirect the copy of the player's heading into another object during cutscenes.

At 0xc5a92 the game copies a 3-float rotation (x, heading, z) from a source
pointer in eax into another object (esi+0x18..0x20):
    mov edx, [eax+4]      (8b 50 04)
    push esi              (56)
    push ebx              (53)
These 5 bytes are replaced by a jmp. The stub redoes them, but while the
cutscene flag is set and eax is the player's rotation triple (player_obj+0x88),
edx is loaded from the captured game heading instead.

Usage:
    python3 install_angle_copy.py <hex_cave_addr> <hex_game_heading_addr>

The cave must be 48 zero bytes. Load a savestate with original bytes first.
"""

import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from gdb_rsp import connect, read_memory, write_memory, cmd_continue # noqa: E402
from keystone import Ks, KS_ARCH_X86, KS_MODE_32 # noqa: E402

HOOK_ADDR = 0x000C5A92
HOOK_LEN = 5
RETURN_ADDR = 0x000C5A97
ORIGINAL = bytes.fromhex("8b50045653")
CUTSCENE_FLAG_ADDR = 0x9DD79C
PLAYER_OBJ_PTR = 0x004EAA04
ROTATION_OFFSET = 0x88
CAVE_SIZE = 48


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
  if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

  cave = int(sys.argv[1], 16)
  game_heading_addr = int(sys.argv[2], 16)
  ks = Ks(KS_ARCH_X86, KS_MODE_32)

  stub = asm(
    ks,
    f"""
        pushfd
        cmp dword ptr [0x{CUTSCENE_FLAG_ADDR:x}], 0
        mov edx, dword ptr [eax + 4]
        je done
        mov edx, dword ptr [0x{PLAYER_OBJ_PTR:x}]
        add edx, 0x{ROTATION_OFFSET:x}
        cmp eax, edx
        mov edx, dword ptr [eax + 4]
        jne done
        mov edx, dword ptr [0x{game_heading_addr:x}]
    done:
        popfd
        push esi
        push ebx
        jmp 0x{RETURN_ADDR:x}
    """,
    cave,
  )
  if len(stub) > CAVE_SIZE:
    raise RuntimeError(f"Stub too large: {len(stub)} bytes")

  hook = asm(ks, f"jmp 0x{cave:x}", HOOK_ADDR)
  if len(hook) != HOOK_LEN:
    raise RuntimeError(f"Expected {HOOK_LEN}-byte jmp, got {len(hook)}")

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

  print("Angle copy redirected during cutscenes.")


if __name__ == "__main__":
  main()
