#!/usr/bin/env python3
"""Replace the game's facing store at 0xd5680 with a player-only version.

Usage:
    python3 install_player_only_facing.py <hex_cave_addr>

Needs the ORIGINAL bytes at 0xd5680 (load a savestate from before the NOP patch).
The cave must be 32 zero bytes.
"""

import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from fastmem import FastMemWriter # noqa: E402
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

HOOK_ADDR = 0x000D5680
HOOK_LEN = 6
RETURN_ADDR = 0x000D5686
ORIGINAL = bytes.fromhex("89868c000000")
PLAYER_OBJ_PTR = 0x004EAA04
CAVE_SIZE = 32


def asm(ks, code, address):
  encoding, _ = ks.asm(code, address)
  return bytes(encoding)


def main():
  cave = int(sys.argv[1], 16)
  ks = Ks(KS_ARCH_X86, KS_MODE_32)
  stub = asm(
    ks,
    f"""
        pushfd
        cmp esi, dword ptr [0x{PLAYER_OBJ_PTR:x}]
        je skip_store
        mov dword ptr [esi + 0x8c], eax
    skip_store:
        popfd
        jmp 0x{RETURN_ADDR:x}

    """,
    cave,
  )
  if len(stub) > CAVE_SIZE:
    raise RuntimeError(f"Stub too large: {len(stub)} bytes")

  hook = asm(ks, f"jmp 0x{cave:x}", HOOK_ADDR)
  hook += b"\x90" * (HOOK_LEN - len(hook))

  mem = FastMemWriter()
  try:
    current = mem.read(HOOK_ADDR, HOOK_LEN)
    if current != ORIGINAL:
      raise RuntimeError(f"Unexpected bytes at 0x{HOOK_ADDR:x}: {current.hex()} (already patched? load the savestate)")

    if mem.read(cave, CAVE_SIZE) != bytes(CAVE_SIZE):
      raise RuntimeError(f"Cave at 0x{cave:x} is not {CAVE_SIZE} zero bytes")

    mem.write_verified(cave, stub, "stub")
    mem.write_verified(HOOK_ADDR, hook, "hook")

  except Exception as e:
    raise (e)

  finally:
    mem.close()

  print("Player-only facing store installed.")


if __name__ == "__main__":
  main()
