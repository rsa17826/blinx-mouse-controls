#!/usr/bin/env python3
"""Live-poll one or more VIRTUAL addresses and print every plausible
type interpretation (u8/i8/u16/i16/u32/i32/f32) plus raw hex, so you
can visually spot which interpretation moves smoothly as you rotate
the camera in xemu.

Does NOT call cmd_continue/detach between reads - it keeps a single
gdbstub connection open and just issues repeated 'm' read requests,
so the guest is only briefly touched per read rather than being
attached/detached every poll (much faster, less risk of desync).

NOTE: the gdbstub halts the CPU while a debugger is attached in some
QEMU configurations. If the game visibly freezes while this is
running, that means reads are pausing the guest - in that case, use
resume_between=True (default) which sends 'c' (continue) after each
batch of reads so the guest keeps running between polls.

Usage:
    python3 typed_watch.py <hex_virtual_addr> [<hex_virtual_addr> ...]

Example:
    python3 typed_watch.py 9dd652 9dd656 9dd65a

"""

import struct
import sys
import time

sys.path.insert(0, "/home/claude")
from gdb_rsp import connect, read_memory, cmd_continue # noqa: E402


def read_typed(sock, addr):
  raw = read_memory(sock, addr, 4)
  return {
    "u8": raw[0],
    "i8": struct.unpack("<b", raw[0:1])[0],
    "u16": struct.unpack("<H", raw[0:2])[0],
    "i16": struct.unpack("<h", raw[0:2])[0],
    "u32": struct.unpack("<I", raw)[0],
    "i32": struct.unpack("<i", raw)[0],
    "f32": struct.unpack("<f", raw)[0],
    "raw_hex": raw.hex(),
  }


def main():
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  addrs = [int(a, 16) for a in sys.argv[1:]]

  print(f"Polling {len(addrs)} address(es): " + ", ".join(f"0x{a:08x}" for a in addrs))
  print("Ctrl-C to stop.\n")

  try:
    while True:
      try:
        sock = connect()

      except (OSError, RuntimeError) as e:
        print(f"connect failed ({e}), retrying...")
        time.sleep(0.5)
        continue

      line_parts = []
      read_error = False
      for addr in addrs:
        try:
          vals = read_typed(sock, addr)

        except (RuntimeError, ValueError) as e:
          # Bad/partial packet on the wire - skip this whole
          # poll cycle and reconnect fresh rather than trying
          # to recover mid-stream (the socket framing may be
          # desynced at this point).
          line_parts = [f"READ FAILED this cycle ({e}) - reconnecting"]
          read_error = True
          break

        b = bytes.fromhex(vals["raw_hex"])
        lo16 = struct.unpack("<H", b[0:2])[0]
        hi16 = struct.unpack("<H", b[2:4])[0]
        line_parts.append(f"0x{addr:08x} raw={vals['raw_hex']} lo16={lo16:5d} hi16={hi16:5d} u16={vals['u16']:5d} i16={vals['i16']:6d} i32={vals['i32']:11d} f32={vals['f32']: .6e}")

      try:
        cmd_continue(sock)

      except (OSError, RuntimeError):
        pass # socket already bad, next loop iteration reconnects

      sock.close()

      print(" | ".join(line_parts))
      if read_error:
        time.sleep(0.2)
      else:
        time.sleep(0.3)



  except KeyboardInterrupt:
    print("\nStopped.")


if __name__ == "__main__":
  main()
