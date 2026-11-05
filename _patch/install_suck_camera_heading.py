#!/usr/bin/env python3
"""Suck cone: use the camera heading (yaw + pi) instead of the player heading.

Hook: `mov ecx,[esi+0x8c]` at 0xd9aa0 (6 bytes), the heading pushed into the
rotation that builds the suck cone axis. For the player object only, ecx is
loaded with (yaw_scratch + pi_scratch) instead. Everything else in the block
(search radius, cone width, other rotations) is untouched.

Usage:
    python3 install_suck_camera_heading.py <hex_cave_addr> <hex_yaw_scratch> <hex_pi_scratch>


pi_scratch is the PI constant scratch from install_asia_mouselook.py
(yaw_scratch + 4). The cave must be 40 zero bytes. The stub keeps no data in
memory (the value goes through the stack), so it never touches a shared slot.
Load a savestate with original bytes first. That also removes
install_suck_direction.py's hook.
"""

import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from gdb_rsp import connect, read_memory, write_memory, cmd_continue
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

HOOK_ADDR = 0x000D9AA0
HOOK_LEN = 6
RETURN_ADDR = 0x000D9AA6
ORIGINAL = bytes.fromhex("8b8e8c000000")
PLAYER_OBJ_PTR = 0x004EAA04
CAVE_SIZE = 40
DATA_SIZE = 0


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
  if len(sys.argv) < 5:
    print(__doc__)
    sys.exit(1)

  cave = int(sys.argv[1], 16)
  yaw_addr = int(sys.argv[2], 16)
  pi_addr = int(sys.argv[3], 16)
  code_addr = cave + DATA_SIZE

  ks = Ks(KS_ARCH_X86, KS_MODE_32)
  stub = asm(
    ks,
    f"""
        mov ecx, dword ptr [esi + 0x8c]
        cmp esi, dword ptr [0x{PLAYER_OBJ_PTR:x}]
        jne back
        fld dword ptr [0x{yaw_addr:x}]
        fadd dword ptr [0x{pi_addr:x}]
        sub esp, 4
        fstp dword ptr [esp]
        pop ecx
        back:

        jmp 0x{RETURN_ADDR:x}
    """,
    code_addr,
  )
  if DATA_SIZE + len(stub) > CAVE_SIZE:
    raise RuntimeError(f"Stub too large: {len(stub)} bytes")

  hook = asm(ks, f"jmp 0x{code_addr:x}", HOOK_ADDR)
  hook += b"\x90" * (HOOK_LEN - len(hook))

  sock = connect()
  try:
    current = read_memory(sock, HOOK_ADDR, HOOK_LEN)
    if current != ORIGINAL:
      raise RuntimeError(f"Unexpected bytes at 0x{HOOK_ADDR:x}: {current.hex()} (already patched? load the savestate)")

    if read_memory(sock, cave, CAVE_SIZE) != bytes(CAVE_SIZE):
      raise RuntimeError(f"Cave at 0x{cave:x} is not {CAVE_SIZE} zero bytes")

    verified_write(sock, code_addr, stub, "stub")
    verified_write(sock, HOOK_ADDR, hook, "hook")

  finally:
    cmd_continue(sock)

  print("Suck camera-heading override installed.")


if __name__ == "__main__":
  main()
