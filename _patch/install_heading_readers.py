#!/usr/bin/env python3
"""Redirect the game's reads of the player's heading (object+0x8c) to the
captured game heading while a cutscene is running.

Each hook is a 6-byte read of [esi+0x8c]. The stub does the original read,
then, only when the cutscene flag is set AND esi is the player object, loads
the captured game heading instead. The spawn read at 0xd4163 is handled by
install_asia_mouselook.py.

Usage:
    python3 install_heading_readers.py <hex_cave_addr> <hex_game_heading_addr>

game_heading_addr is mouselook's cave + 208 + 24 (0x141fcd for cave 0x141ee5).
The cave must be 240 zero bytes. Load a savestate with original bytes first.
"""

import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from gdb_rsp import connect, read_memory, write_memory, cmd_continue # noqa: E402
from keystone import Ks, KS_ARCH_X86, KS_MODE_32 # noqa: E402

CUTSCENE_FLAG_ADDR = 0x9DD79C
PLAYER_OBJ_PTR = 0x004EAA04
HOOK_LEN = 6
STUB_SLOT = 40

# (hook address, original bytes, destination: a register, or "fld" for an x87 load)
HOOKS = [
  (0x000D52C4, "8b868c000000", "eax"),
  (0x000D5D85, "8b968c000000", "edx"),
  (0x000D8D67, "8b968c000000", "edx"),
  (0x000DB59E, "8b8e8c000000", "ecx"),
  (0x000A05C7, "d9868c000000", "fld"),
  (0x000D8A0C, "8b968c000000", "edx"),
]


def asm(ks, code, address):
  encoding, _ = ks.asm(code, address)
  return bytes(encoding)


def build_stub(ks, cave, dest, return_addr, game_heading_addr):
  if dest == "fld":
    code = f"""
        pushfd
        cmp dword ptr [0x{CUTSCENE_FLAG_ADDR:x}], 0
        je normal
        cmp esi, dword ptr [0x{PLAYER_OBJ_PTR:x}]
        jne normal
        fld dword ptr [0x{game_heading_addr:x}]
        jmp done
    normal:
        fld dword ptr [esi + 0x8c]
    done:
        popfd
        jmp 0x{return_addr:x}
    """
  else:
    code = f"""
        pushfd
        mov {dest}, dword ptr [esi + 0x8c]
        cmp dword ptr [0x{CUTSCENE_FLAG_ADDR:x}], 0
        je done
        cmp esi, dword ptr [0x{PLAYER_OBJ_PTR:x}]
        jne done
        mov {dest}, dword ptr [0x{game_heading_addr:x}]
    done:
        popfd
        jmp 0x{return_addr:x}
    """

  stub = asm(ks, code, cave)
  if len(stub) > STUB_SLOT:
    raise RuntimeError(f"Stub for {dest} too large: {len(stub)} bytes")

  return stub


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
  total = STUB_SLOT * len(HOOKS)

  plan = []
  for i, (hook_addr, original, dest) in enumerate(HOOKS):
    stub_addr = cave + i * STUB_SLOT
    stub = build_stub(ks, stub_addr, dest, hook_addr + HOOK_LEN, game_heading_addr)
    jmp = asm(ks, f"jmp 0x{stub_addr:x}", hook_addr)
    jmp += b"\x90" * (HOOK_LEN - len(jmp))
    plan.append((hook_addr, bytes.fromhex(original), stub_addr, stub, jmp))

  sock = connect()
  try:
    for hook_addr, original, _, _, _ in plan:
      current = read_memory(sock, hook_addr, HOOK_LEN)
      if current != original:
        raise RuntimeError(f"Unexpected bytes at 0x{hook_addr:x}: {current.hex()} (already patched? load the savestate)")

    if read_memory(sock, cave, total) != bytes(total):
      raise RuntimeError(f"Cave at 0x{cave:x} is not {total} zero bytes")

    for hook_addr, _, stub_addr, stub, _ in plan:
      verified_write(sock, stub_addr, stub, f"stub for 0x{hook_addr:x}")

    for hook_addr, _, _, _, jmp in plan:
      verified_write(sock, hook_addr, jmp, f"hook 0x{hook_addr:x}")

  finally:
    cmd_continue(sock)

  print("Heading readers redirected during cutscenes.")


if __name__ == "__main__":
  main()
