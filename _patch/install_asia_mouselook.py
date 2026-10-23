#!/usr/bin/env python3
"""Install the mouse-look FULL-OVERRIDE patch for the ASIA build.

Hooks two 6-byte FMUL instructions:
    pitch: 0x0002316d
    yaw:   0x00023183

The yaw trampoline loads the camera yaw onto the FPU stack, duplicates it
via stack memory to add an automatic 180-degree (pi) offset, writes it to
the player struct (+0x24 heading), then adds a separate, independently
tunable "render_yaw_offset" scratch value (default 0.0) to the ORIGINAL
copy before leaving it for the game to render as the camera's own facing.

render_yaw_offset exists so install_asia_position.py can make the camera
always look toward the player: since forward_offset there is a fixed
constant chosen at install time, the required look-at-player yaw
correction is always exactly 0 or pi (never anything in between), decided
once by forward_offset's sign - no per-frame atan2 needed. This script
initializes render_yaw_offset to 0.0
in place after this patch is installed.

Requires keystone-engine:
    pip install keystone-engine --break-system-packages

Usage:
    python3 install_asia_mouselook.py <hex_cave_addr>

"""

import struct
import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../lib')))
from gdb_rsp import connect, read_memory, write_memory, cmd_continue # noqa: E402

try:
  from keystone import Ks, KS_ARCH_X86, KS_MODE_32

except ImportError:
  print("keystone-engine not installed. Run:")
  print("  pip install keystone-engine --break-system-packages")
  sys.exit(1)

PLAYER_PTR_ADDR = 0x009DD680
HEADING_OFFSET = 0x24

PITCH_HOOK_ADDR = 0x0002316D
PITCH_HOOK_LEN = 6
PITCH_RETURN_ADDR = 0x00023173

YAW_HOOK_ADDR = 0x00023183
YAW_HOOK_LEN = 6
YAW_RETURN_ADDR = 0x00023189

ROLL_HOOK_ADDR = 0x00023199
ROLL_HOOK_LEN = 6
ROLL_RETURN_ADDR = 0x0002319F

TRAMPOLINE_BUDGET = 64

CUTSCENE_FLAG_ADDR = 0x9DD79C
FMUL_ABS_PREFIX = bytes.fromhex("d80d")
TAIL_SIZE = 16


def cutscene_check(tail_addr):
  return f"""
        cmp dword ptr [0x{CUTSCENE_FLAG_ADDR:x}], 0
        jne 0x{tail_addr:x}
    """


def build_original_tail(ks, tail_addr, original, return_addr):
  # if original[:2] != FMUL_ABS_PREFIX:
  #   raise RuntimeError(f"Original bytes at hook are not fmul [abs32]: {original.hex()}")

  return original + asm(ks, f"jmp 0x{return_addr:x}", tail_addr + len(original))


def asm(ks, code, address):
  encoding, count = ks.asm(code, address)
  if encoding is None:
    raise RuntimeError(f"Failed to assemble at 0x{address:x}:\n{code}")

  return bytes(encoding)


def build_pitch_trampoline(ks, cave_addr, value_addr, return_addr, tail_addr):
  code = f"""
        {cutscene_check(tail_addr)}
        fstp st(0)
        fld dword ptr [0x{value_addr:x}]
        jmp 0x{return_addr:x}
    """
  encoded = asm(ks, code, cave_addr)
  if len(encoded) > TRAMPOLINE_BUDGET:
    raise RuntimeError(f"Pitch trampoline exceeds budget ({len(encoded)} bytes).")

  return encoded


def build_yaw_trampoline(ks, cave_addr, value_addr, pi_scratch, render_yaw_offset_addr, return_addr, heading_offset_addr, tail_addr):
  code = f"""
        {cutscene_check(tail_addr)}
        fstp st(0)
        fld dword ptr [0x{value_addr:x}]
        push eax
        push edx
        mov edx, 0x{PLAYER_PTR_ADDR:x}
        mov eax, dword ptr [edx]
        test eax, eax
        jz skip_heading
        fld st(0)
        fadd dword ptr [0x{pi_scratch:x}]
        fadd dword ptr [0x{heading_offset_addr:x}]
        fstp dword ptr [eax + 0x{HEADING_OFFSET:x}]
    skip_heading:
        fadd dword ptr [0x{render_yaw_offset_addr:x}]
        pop edx
        pop eax
        jmp 0x{return_addr:x}

    """
  encoded = asm(ks, code, cave_addr)
  if len(encoded) > TRAMPOLINE_BUDGET:
    raise RuntimeError(f"Yaw trampoline exceeds budget ({len(encoded)} bytes).")

  return encoded


def build_roll_trampoline(ks, cave_addr, return_addr):
  code = f"""
        fstp st(0)
        fldz
        jmp 0x{return_addr:x}
    """
  encoded = asm(ks, code, cave_addr)
  if len(encoded) > TRAMPOLINE_BUDGET:
    raise RuntimeError(f"Roll trampoline exceeds budget ({len(encoded)} bytes).")

  return encoded


def build_hook_jmp(ks, hook_addr, hook_len, target_addr):
  code = f"jmp 0x{target_addr:x}"
  encoded = asm(ks, code, hook_addr)
  if len(encoded) != 5:
    raise RuntimeError(f"Expected a 5-byte jmp, got {len(encoded)} bytes.")

  padding = bytes([0x90] * (hook_len - len(encoded)))
  return encoded + padding


def verified_write(sock, addr, data, label):
  write_memory(sock, addr, data)
  readback = read_memory(sock, addr, len(data))
  if readback != data:
    raise RuntimeError(f"Write verification FAILED for {label} at 0x{addr:x}: wrote {data.hex()}, read back {readback.hex()}.")

  print(f"  verified write OK: {label} at 0x{addr:08x} ({len(data)} bytes)")


def main():
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  cave_addr = int(sys.argv[1], 16)
  ks = Ks(KS_ARCH_X86, KS_MODE_32)

  sock = connect()

  orig_pitch = read_memory(sock, PITCH_HOOK_ADDR, PITCH_HOOK_LEN)
  orig_yaw = read_memory(sock, YAW_HOOK_ADDR, YAW_HOOK_LEN)
  orig_roll = read_memory(sock, ROLL_HOOK_ADDR, ROLL_HOOK_LEN)

  pitch_trampoline_addr = cave_addr
  yaw_trampoline_addr = cave_addr + TRAMPOLINE_BUDGET
  roll_trampoline_addr = cave_addr + 2 * TRAMPOLINE_BUDGET
  pitch_value_addr = cave_addr + 3 * TRAMPOLINE_BUDGET
  yaw_value_addr = pitch_value_addr + 4
  pi_scratch_addr = yaw_value_addr + 4
  render_yaw_offset_addr = pi_scratch_addr + 4

  heading_offset_addr = render_yaw_offset_addr + 4
  pitch_tail_addr = pitch_trampoline_addr + 40
  yaw_tail_addr = roll_trampoline_addr + 16

  print(f"Cave base:            0x{cave_addr:08x}")
  print(f"Pitch trampoline:     0x{pitch_trampoline_addr:08x}")
  print(f"Yaw trampoline:       0x{yaw_trampoline_addr:08x}")
  print(f"Roll trampoline:      0x{roll_trampoline_addr:08x} (zeroes the garbage roll input)")
  print(f"Pitch value scratch:  0x{pitch_value_addr:08x}")
  print(f"Yaw value scratch:    0x{yaw_value_addr:08x}")
  print(f"PI constant scratch:  0x{pi_scratch_addr:08x}")
  print(f"Render yaw offset:    0x{render_yaw_offset_addr:08x} (0.0 by default)")
  print(f"Pitch tail:           0x{pitch_tail_addr:08x}")
  print(f"Yaw tail:             0x{yaw_tail_addr:08x}")

  pitch_tail_code = build_original_tail(ks, pitch_tail_addr, orig_pitch, PITCH_RETURN_ADDR)
  yaw_tail_code = build_original_tail(ks, yaw_tail_addr, orig_yaw, YAW_RETURN_ADDR)

  for addr in (pitch_tail_addr, yaw_tail_addr):
    if read_memory(sock, addr, TAIL_SIZE) != bytes(TAIL_SIZE):
      raise RuntimeError(f"Tail area at 0x{addr:x} is not zero. Load a savestate first.")


  pitch_trampoline_code = build_pitch_trampoline(ks, pitch_trampoline_addr, pitch_value_addr, PITCH_RETURN_ADDR, pitch_tail_addr)
  yaw_trampoline_code = build_yaw_trampoline(ks, yaw_trampoline_addr, yaw_value_addr, pi_scratch_addr, render_yaw_offset_addr, YAW_RETURN_ADDR, heading_offset_addr, yaw_tail_addr)
  roll_trampoline_code = build_roll_trampoline(ks, roll_trampoline_addr, ROLL_RETURN_ADDR)

  pitch_hook_bytes = build_hook_jmp(ks, PITCH_HOOK_ADDR, PITCH_HOOK_LEN, pitch_trampoline_addr)
  yaw_hook_bytes = build_hook_jmp(ks, YAW_HOOK_ADDR, YAW_HOOK_LEN, yaw_trampoline_addr)
  roll_hook_bytes = build_hook_jmp(ks, ROLL_HOOK_ADDR, ROLL_HOOK_LEN, roll_trampoline_addr)

  print(f"\nOriginal pitch hook bytes: {orig_pitch.hex()} (save for manual revert)")
  print(f"Original yaw hook bytes:   {orig_yaw.hex()} (save for manual revert)")
  print(f"Original roll hook bytes:  {orig_roll.hex()} (save for manual revert)")

  print()
  try:
    verified_write(sock, pitch_tail_addr, pitch_tail_code, "pitch tail")
    verified_write(sock, yaw_tail_addr, yaw_tail_code, "yaw tail")

    verified_write(sock, pitch_trampoline_addr, pitch_trampoline_code, "pitch trampoline")
    verified_write(sock, yaw_trampoline_addr, yaw_trampoline_code, "yaw trampoline")
    verified_write(sock, roll_trampoline_addr, roll_trampoline_code, "roll trampoline")

    current_pitch = read_memory(sock, 0x009DD7E0, 4)
    current_yaw = read_memory(sock, 0x009DD7E4, 4)
    verified_write(sock, pitch_value_addr, current_pitch, "pitch value scratch (init)")
    verified_write(sock, yaw_value_addr, current_yaw, "yaw value scratch (init)")

    verified_write(sock, heading_offset_addr, struct.pack("<f", 0.0), "heading offset (init)")

    pi_bytes = struct.pack("<f", 3.14159265)
    verified_write(sock, pi_scratch_addr, pi_bytes, "pi constant scratch (init)")
    verified_write(sock, render_yaw_offset_addr, struct.pack("<f", 0.0), "render yaw offset (init)")

    verified_write(sock, PITCH_HOOK_ADDR, pitch_hook_bytes, "pitch hook jmp")
    verified_write(sock, YAW_HOOK_ADDR, yaw_hook_bytes, "yaw hook jmp")
    verified_write(sock, ROLL_HOOK_ADDR, roll_hook_bytes, "roll hook jmp")

  except RuntimeError as e:
    print(f"\n{e}")
    print("Patch NOT fully installed - re-run this script.")
    cmd_continue(sock)
    sys.exit(1)

  cmd_continue(sock)

  print("\nPatch installed successfully.")
  print(f"  Yaw value scratch:   0x{yaw_value_addr:08x}")
  print(f"  Render yaw offset:   0x{render_yaw_offset_addr:08x}")


if __name__ == "__main__":
  main()
