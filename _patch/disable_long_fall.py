#!/usr/bin/env python3
"""Disable the long-fall state (player+2 = 0x15) and its sound (0x807).

The ground-check helper ends with a "no ground below" block at 0xd4203 that
sets player+2 = 0x15 and calls update_score(0x807, ...). This replaces that
block with the helper's normal return epilogue:
    mov eax,1 ; pop esi ; add esp,0x4c ; ret

so the helper always behaves as if ground was found. It affects every caller
of the helper, including the suck code.

Usage:
    python3 disable_long_fall.py

Needs the ORIGINAL bytes: load a savestate from before this patch.
"""

import sys, os

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
from fastmem import FastMemWriter # noqa: E402

EPILOGUE_ADDR = 0x000D41FE
EPILOGUE = bytes.fromhex("5e83c44cc3")
BLOCK_ADDR = 0x000D4203
EXPECTED = bytes.fromhex("6a0068001000006aff680708000066c7465e0000c6460215c7861c01000000000000")
NEW = bytes.fromhex("b8010000005e83c44cc3").ljust(len(EXPECTED), b"\x90")


def main():
  mem = FastMemWriter()
  try:
    epilogue = mem.read(EPILOGUE_ADDR, len(EPILOGUE))
    if epilogue != EPILOGUE:
      raise RuntimeError(f"Unexpected epilogue at 0x{EPILOGUE_ADDR:x}: {epilogue.hex()} (expected {EPILOGUE.hex()})")

    current = mem.read(BLOCK_ADDR, len(EXPECTED))
    if current != EXPECTED:
      raise RuntimeError(f"Unexpected bytes at 0x{BLOCK_ADDR:x}: {current.hex()} (already patched? load the savestate)")

    mem.write_verified(BLOCK_ADDR, NEW, "long-fall block -> normal return")

  except Exception as e:
    raise (e)

  finally:
    mem.close()

  print("Long-fall state disabled.")


if __name__ == "__main__":
  main()
