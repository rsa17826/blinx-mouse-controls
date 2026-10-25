#!/usr/bin/env python3
"""Override the player's shot direction (player+0x160..0x168) from mouse yaw/pitch.

Hook: the call at 0xdcc47 (`call 0x2b3b0`) that writes the animated muzzle
direction into player+0x160. It is replaced by a call into a cave that makes
the original call, then (player object only) overwrites the direction with
    x = sin(yaw) * cos(p), y = sign * sin(p), z = cos(yaw) * cos(p)

Usage:
    python3 install_shot_direction.py <hex_cave_addr> <hex_pitch_scratch> <hex_yaw_scratch> <pitch_sign: 1 or -1>

The cave must be 128 zero bytes. Requires install_asia_mouselook.py installed
(pitch/yaw scratch floats). Load a savestate with original bytes first.
"""

import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from fastmem import FastMemWriter  # noqa: E402
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

HOOK_ADDR = 0x000DCC47
HOOK_LEN = 5
ORIGINAL = bytes.fromhex("e864e7f4ff")
CALLEE = 0x0002B3B0
PLAYER_OBJ_PTR = 0x004EAA04
DIR_X = 0x160
DIR_Y = 0x164
DIR_Z = 0x168
CAVE_SIZE = 128


def asm(ks, code, address):
  encoding, _ = ks.asm(code, address)
  return bytes(encoding)


def main():
  if len(sys.argv) < 5:
    print(__doc__)
    sys.exit(1)

  cave = int(sys.argv[1], 16)
  pitch_addr = int(sys.argv[2], 16)
  yaw_addr = int(sys.argv[3], 16)
  pitch_sign = int(sys.argv[4])
  if pitch_sign not in (1, -1):
    raise RuntimeError("pitch_sign must be 1 or -1")

  ret_slot = cave
  cp_slot = cave + 4
  code_addr = cave + 8
  negate = "fchs" if pitch_sign == -1 else ""

  ks = Ks(KS_ARCH_X86, KS_MODE_32)
  # @noregex
  # NOTE use this to allow y direction changes
  # stub = asm(
  #   ks,
  #   """
  #       pop dword ptr [0x{ret_slot:x}]
  #       call 0x{CALLEE:x}
  #       cmp esi, dword ptr [0x{PLAYER_OBJ_PTR:x}]
  #       jne finish
  #       fld dword ptr [0x{pitch_addr:x}]
  #       fsincos
  #       fstp dword ptr [0x{cp_slot:x}]
  #       {negate}
  #       fstp dword ptr [esi + 0x{DIR_Y:x}]
  #       fld dword ptr [0x{yaw_addr:x}]
  #       fsincos
  #       fmul dword ptr [0x{cp_slot:x}]
  #       fstp dword ptr [esi + 0x{DIR_Z:x}]
  #       fmul dword ptr [0x{cp_slot:x}]
  #       fstp dword ptr [esi + 0x{DIR_X:x}]
  #   finish:
  #       push dword ptr [0x{ret_slot:x}]
  #       ret
  #   """,
  #   code_addr,
  # )
  stub = asm(
    ks,
    f"""
        pop dword ptr [0x{ret_slot:x}]
        call 0x{CALLEE:x}
        cmp esi, dword ptr [0x{PLAYER_OBJ_PTR:x}]
        jne finish

        fldz
        fstp dword ptr [esi + 0x{DIR_Y:x}]

        fld dword ptr [0x{yaw_addr:x}]
        fsincos
        fstp dword ptr [esi + 0x{DIR_Z:x}]
        fstp dword ptr [esi + 0x{DIR_X:x}]
    finish:
        push dword ptr [0x{ret_slot:x}]
        ret

    """,
    code_addr,
  )
  if 8 + len(stub) > CAVE_SIZE:
    raise RuntimeError(f"Stub too large: {len(stub)} bytes")

  hook = asm(ks, f"call 0x{code_addr:x}", HOOK_ADDR)
  if len(hook) != HOOK_LEN:
    raise RuntimeError(f"Expected {HOOK_LEN}-byte call, got {len(hook)}")

  mem = FastMemWriter()
  try:
    current = mem.read(HOOK_ADDR, HOOK_LEN)
    if current != ORIGINAL:
      raise RuntimeError(f"Unexpected bytes at 0x{HOOK_ADDR:x}: {current.hex()} (already patched? load the savestate)")

    if mem.read(cave, CAVE_SIZE) != bytes(CAVE_SIZE):
      raise RuntimeError(f"Cave at 0x{cave:x} is not {CAVE_SIZE} zero bytes")

    mem.write_verified(code_addr, stub, "stub")
    mem.write_verified(HOOK_ADDR, hook, "hook")

  except Exception as e:
    raise (e)

  finally:
    mem.close()

  print("Shot direction override installed.")


if __name__ == "__main__":
  main()
