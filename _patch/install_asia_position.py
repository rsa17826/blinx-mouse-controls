#!/usr/bin/env python3
"""Install the FIRST-PERSON position-override patch for the ASIA build,
on top of the pitch/yaw patch from install_asia_mouselook.py.
Position is computed ENTIRELY IN-GUEST from the player-position
pointer (0x9dd680), plus a yaw scratch float maintained by
mouse_hook_fast.py. Supports eye height on Y and a view-aligned
forward/backward distance offset that tracks the mouse-driven look
angle directly, independent of the engine's own camera-yaw field
(which the game's auto-follow camera also writes to).
Hooks three 6-byte FLD instructions in FUN_00022fb0 that load the
camera's fixed rig-offset before adding the orbit delta:
    X: 0x0002312c (preserves EAX side-effect for roll calculation)
    Y: 0x00023141
    Z: 0x00023151

Requires keystone-engine. Requires install_asia_mouselook.py already installed
(the UPDATED version with the render_yaw_offset scratch - this script writes
into that scratch, at yaw_scratch_addr + 8, to make the camera always face
the player regardless of forward_offset's sign).
Usage:
    python3 install_asia_position.py <hex_cave_addr> <hex_yaw_scratch_addr> [eye_height] [forward_offset]
    hex_yaw_scratch_addr: the "Yaw value scratch" address printed by
        install_asia_mouselook.py - the float mouse_hook_fast.py writes raw
        mouse-driven yaw into. Required: this is what the offset is computed
        relative to (the engine's own camera-yaw field is not used, since the
        game's auto-follow camera also writes it).
    eye_height: float added to player_pos.y (default 15.0)
    forward_offset: float distance along view vector (+ = behind, - = ahead, default 0.0)

"""

import struct
import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from fastmem import FastMemWriter # noqa: E402

try:
  from keystone import Ks, KS_ARCH_X86, KS_MODE_32

except ImportError:
  print("keystone-engine not installed. Run:")
  print("  pip install keystone-engine --break-system-packages")
  sys.exit(1)

PLAYER_PTR_ADDR = 0x009DD680


# NOTE: 0x9DD7E4 is NOT used as the yaw source. It's the engine's own render-yaw
# field, and on this game the camera has its own auto-follow/recenter logic that
# also writes there — reading it caused the position offset to alternate between
# "behind player" and "flipped" depending on which writer won that frame.
# Instead we read the yaw scratch float that mouse_hook_fast.py itself maintains
# directly from raw mouse deltas (its `yaw_addr` arg) — never touched by the engine.
def signed(rel):
  """Format a relative offset for inline asm, e.g. '+ 4' or '- 12', avoiding
  the invalid '+ -12' keystone chokes on when rel is negative."""
  return f"+ {rel}" if rel >= 0 else f"- {-rel}"


X_HOOK_ADDR = 0x0002312C
X_HOOK_LEN = 6
X_RETURN_ADDR = 0x0002313D
X_SIDE_EFFECT_TARGET = 0x009DD750
Y_HOOK_ADDR = 0x00023141
Y_HOOK_LEN = 6
Y_RETURN_ADDR = 0x0002314D
Z_HOOK_ADDR = 0x00023151
Z_HOOK_LEN = 6
Z_RETURN_ADDR = 0x0002315D
TRAMPOLINE_BUDGET = 96


def asm(ks, code, address):
  encoding, count = ks.asm(code, address)
  if encoding is None:
    raise RuntimeError(f"Failed to assemble at 0x{address:x}:\n{code}")

  return bytes(encoding)


def build_x_trampoline(ks, cave_addr, forward_offset_addr, sin_scratch_addr, cos_scratch_addr, yaw_scratch_addr):
  # Computes sin/cos of the raw mouse-driven yaw (yaw_scratch_addr, maintained
  # directly by mouse_hook_fast.py) rather than the engine's own render-yaw field,
  # which the game's auto-follow camera also writes to.
  # X = forward_offset * sin(yaw) + player_pos.x
  # X_SIDE_EFFECT_TARGET feeds a downstream ROLL calculation (per original
  # disassembly) that expects a SMALL rig-relative offset, not a full world
  # coordinate. Storing the final (post player_pos) value there made the roll
  # swing wildly with yaw (visible as the camera flipping upside down and
  # back while turning). Store the local offset (pre player_pos) instead -
  # same small magnitude range the original rig constant had - then add
  # player_pos.x afterward purely for the returned camera position.
  # NOTE: keystone on this build rejects any ';' asm comment inside the code
  # string with KS_ERR_ASM_INVALIDOPERAND, so notes live here in Python instead.
  f_offset_rel = forward_offset_addr - cave_addr
  sin_rel = sin_scratch_addr - cave_addr
  cos_rel = cos_scratch_addr - cave_addr
  code = f"""
        pushfd
        pushad
        mov ebx, 0x{cave_addr:x}
        mov ecx, dword ptr [0x{PLAYER_PTR_ADDR:x}]
        test ecx, ecx
        jz fallback_x
        fld dword ptr [0x{yaw_scratch_addr:x}]
        fsincos
        fstp dword ptr [ebx {signed(cos_rel)}]
        fstp dword ptr [ebx {signed(sin_rel)}]
        fld dword ptr [ebx {signed(f_offset_rel)}]
        fmul dword ptr [ebx {signed(sin_rel)}]
        sub esp, 4
        fst dword ptr [esp]
        pop eax
        mov dword ptr [0x{X_SIDE_EFFECT_TARGET:x}], eax
        fadd dword ptr [ecx]
        jmp finish_x

fallback_x:
        fld dword ptr [0x9dd724]
        fadd dword ptr [0x9dd6b4]

finish_x:
        popad
        popfd
        jmp 0x{X_RETURN_ADDR:x}
  """
  encoded = asm(ks, code, cave_addr)
  if len(encoded) > TRAMPOLINE_BUDGET:
    raise RuntimeError(f"X trampoline too large: {len(encoded)} bytes")

  return encoded


def build_y_trampoline(ks, cave_addr, eye_height_addr):
  e_height_rel = eye_height_addr - cave_addr
  code = f"""
        pushfd
        pushad
        mov ebx, 0x{cave_addr:x}
        mov ecx, dword ptr [0x{PLAYER_PTR_ADDR:x}]
        test ecx, ecx
        jz fallback_y
        fld dword ptr [ecx + 4]
        fadd dword ptr [ebx {signed(e_height_rel)}]
        popad
        popfd
        jmp 0x{Y_RETURN_ADDR:x}

fallback_y:
        fld dword ptr [0x9dd728]
        fadd dword ptr [0x9dd6b8]
        popad
        popfd
        jmp 0x{Y_RETURN_ADDR:x}
  """
  encoded = asm(ks, code, cave_addr)
  if len(encoded) > TRAMPOLINE_BUDGET:
    raise RuntimeError(f"Y trampoline too large: {len(encoded)} bytes")

  return encoded


def build_z_trampoline(ks, cave_addr, forward_offset_addr, cos_scratch_addr):
  # Z = forward_offset * cos(yaw) + player_pos.z
  # NOTE: relies on build_x_trampoline having run first this frame to populate
  # cos_scratch from the mouse-driven yaw scratch.
  f_offset_rel = forward_offset_addr - cave_addr
  cos_rel = cos_scratch_addr - cave_addr
  code = f"""
        pushfd
        pushad
        mov ebx, 0x{cave_addr:x}
        mov ecx, dword ptr [0x{PLAYER_PTR_ADDR:x}]
        test ecx, ecx
        jz fallback_z
        fld dword ptr [ebx {signed(f_offset_rel)}]
        fmul dword ptr [ebx {signed(cos_rel)}]
        fadd dword ptr [ecx + 8]
        jmp finish_z

fallback_z:
        fld dword ptr [0x9dd72c]
        fadd dword ptr [0x9dd6bc]

finish_z:
        popad
        popfd
        jmp 0x{Z_RETURN_ADDR:x}
  """
  encoded = asm(ks, code, cave_addr)
  if len(encoded) > TRAMPOLINE_BUDGET:
    raise RuntimeError(f"Z trampoline too large: {len(encoded)} bytes")

  return encoded


def build_hook_jmp(ks, hook_addr, hook_len, target_addr):
  code = f"jmp 0x{target_addr:x}"
  encoded = asm(ks, code, hook_addr)
  if len(encoded) != 5:
    raise RuntimeError(f"Expected 5-byte jmp, got {len(encoded)} bytes")

  return encoded + bytes([0x90] * (hook_len - len(encoded)))


def main():
  if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

  cave_addr = int(sys.argv[1], 16)
  yaw_scratch_addr = int(sys.argv[2], 16)
  eye_height = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
  forward_offset = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
  ks = Ks(KS_ARCH_X86, KS_MODE_32)
  # Layout: Data variables packed at the very start of the cave (offsets 0-15)
  eye_height_addr = cave_addr
  forward_offset_addr = cave_addr + 4
  sin_scratch_addr = cave_addr + 8
  cos_scratch_addr = cave_addr + 12
  # Trampolines start after the data block
  x_trampoline_addr = cave_addr + 16
  y_trampoline_addr = x_trampoline_addr + TRAMPOLINE_BUDGET
  z_trampoline_addr = y_trampoline_addr + TRAMPOLINE_BUDGET
  print(f"Cave base:              0x{cave_addr:08x}")
  print(f"Eye height offset:      {eye_height} (scratch @ 0x{eye_height_addr:08x})")
  print(f"Forward offset:         {forward_offset} (scratch @ 0x{forward_offset_addr:08x})")
  print(f"Yaw source:             0x{yaw_scratch_addr:08x} (mouse_hook_fast.py's raw yaw, not engine field)")
  # The render_yaw_offset scratch lives right after mouselook's pi_scratch, which
  # itself lives right after yaw_scratch (see install_asia_mouselook.py's cave
  # layout: pitch_value, yaw_value, pi_scratch, render_yaw_offset - each 4 bytes).
  render_yaw_offset_addr = yaw_scratch_addr + 8
  # Since forward_offset is a fixed constant, the look-at-player yaw correction
  # is always exactly 0 or pi (never in between) - see conversation for the
  # derivation. forward_offset > 0 (camera behind player) needs +pi; < 0 (camera
  # ahead of player) needs +0.
  render_yaw_offset = 3.14159265 if forward_offset > 0 else 0.0
  print(f"Render yaw offset:      {render_yaw_offset} (writing to 0x{render_yaw_offset_addr:08x}, from mouselook's cave)")
  x_code = build_x_trampoline(ks, x_trampoline_addr, forward_offset_addr, sin_scratch_addr, cos_scratch_addr, yaw_scratch_addr)
  y_code = build_y_trampoline(ks, y_trampoline_addr, eye_height_addr)
  z_code = build_z_trampoline(ks, z_trampoline_addr, forward_offset_addr, cos_scratch_addr)
  x_hook = build_hook_jmp(ks, X_HOOK_ADDR, X_HOOK_LEN, x_trampoline_addr)
  y_hook = build_hook_jmp(ks, Y_HOOK_ADDR, Y_HOOK_LEN, y_trampoline_addr)
  z_hook = build_hook_jmp(ks, Z_HOOK_ADDR, Z_HOOK_LEN, z_trampoline_addr)
  mem = FastMemWriter()
  orig_x = mem.read(X_HOOK_ADDR, X_HOOK_LEN)
  orig_y = mem.read(Y_HOOK_ADDR, Y_HOOK_LEN)
  orig_z = mem.read(Z_HOOK_ADDR, Z_HOOK_LEN)
  print(f"\nOriginal X/Y/Z hook bytes: {orig_x.hex()} / {orig_y.hex()} / {orig_z.hex()}")
  print()
  try:
    mem.write_verified(eye_height_addr, struct.pack("<f", eye_height), "eye height const")
    mem.write_verified(forward_offset_addr, struct.pack("<f", forward_offset), "forward offset const")
    mem.write_verified(render_yaw_offset_addr, struct.pack("<f", render_yaw_offset), "render yaw offset (in mouselook's cave)")
    mem.write_verified(x_trampoline_addr, x_code, "X trampoline")
    mem.write_verified(y_trampoline_addr, y_code, "Y trampoline")
    mem.write_verified(z_trampoline_addr, z_code, "Z trampoline")
    mem.write_verified(X_HOOK_ADDR, x_hook, "X hook jmp")
    mem.write_verified(Y_HOOK_ADDR, y_hook, "Y hook jmp")
    mem.write_verified(Z_HOOK_ADDR, z_hook, "Z hook jmp")

  except RuntimeError as e:
    print(f"\n{e}\nPatch NOT fully installed - re-run this script.")
    mem.close()
    sys.exit(1)

  mem.close()
  print(f"\nPosition patch installed - camera orbits player at any look angle,")
  print(f"always facing the player ({forward_offset:+.1f} offset along view vector).")
  print(f"To tune dynamically without reinstalling:")
  print(f"  - Forward offset: write float32 to 0x{forward_offset_addr:08x}")
  print(f"  - NOTE: if you change forward_offset's sign at runtime, also flip")
  print(f"    render_yaw_offset (0.0 <-> pi) at 0x{render_yaw_offset_addr:08x}, or")
  print(f"    the camera will face away from the player instead of toward it.")


if __name__ == "__main__":
  main()
