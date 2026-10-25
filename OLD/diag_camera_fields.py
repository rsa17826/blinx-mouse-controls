#!/usr/bin/env python3
"""Live diagnostic: repeatedly halt/read/resume the guest to print the camera's
actual pitch/yaw/roll render fields alongside our own injected scratch values,
so we can see what's really happening at runtime instead of guessing from
static analysis of FUN_00022fb0.

Move the mouse LEFT/RIGHT ONLY while this runs (reproduce the bug) and watch
which fields move and by how much each sample.

Usage:
    python3 diag_camera_fields.py <hex_pitch_scratch_addr> <hex_yaw_scratch_addr> [interval_sec]

    hex_pitch_scratch_addr / hex_yaw_scratch_addr: the values printed by
        install_asia_mouselook.py ("Pitch value scratch" / "Yaw value scratch")
    interval_sec: how long to let the guest run between samples (default 0.3)

Each sample causes a brief hitch (halt -> read -> resume), which is expected -
this is a diagnostic, not something to leave running during normal play.
"""

import struct
import sys
import time

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory, cmd_continue # noqa: E402

# Fixed addresses from the decompiled FUN_00022fb0 / earlier reads in this
# conversation - these are the engine's OWN pitch/yaw/roll render fields and
# the smoothing blend factor, not our injected scratch.
CAM_PITCH_OUT = 0x009DD7E0
CAM_YAW_OUT = 0x009DD7E4
CAM_ROLL_OUT = 0x009DD7E8 # inferred from the DAT_009dd7e0/7e4/7e8 naming pattern in the decompile - unverified, watch for whether it moves sensibly
BLEND_FACTOR_GUESS = None # address of DAT_009dd7dc unknown - not polled


def read_f32(sock, addr):
  return struct.unpack("<f", read_memory(sock, addr, 4))[0]


def main():
  if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

  pitch_scratch_addr = int(sys.argv[1], 16)
  yaw_scratch_addr = int(sys.argv[2], 16)
  interval = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3

  sock = connect()

  print(f"Polling every {interval}s. Ctrl-C to stop.")
  print(f"{'t':>6}  {'our_pitch':>10}  {'our_yaw':>10}  {'cam_pitch':>10}  {'cam_yaw':>10}  {'cam_roll':>10}")

  t0 = time.time()
  try:
    while True:
      our_pitch = read_f32(sock, pitch_scratch_addr)
      our_yaw = read_f32(sock, yaw_scratch_addr)
      cam_pitch = read_f32(sock, CAM_PITCH_OUT)
      cam_yaw = read_f32(sock, CAM_YAW_OUT)
      cam_roll = read_f32(sock, CAM_ROLL_OUT)

      t = time.time() - t0
      print(f"{t:6.1f}  {our_pitch:10.4f}  {our_yaw:10.4f}  {cam_pitch:10.4f}  {cam_yaw:10.4f}  {cam_roll:10.4f}")

      cmd_continue(sock)
      time.sleep(interval)

      # Interrupt (standard gdb remote break character) to halt again for
      # the next sample.
      sock.sendall(b"\x03")
      # Drain the resulting stop-reply so it doesn't desync the next command.
      buf = b""
      sock.settimeout(2.0)
      try:
        while b"#" not in buf or len(buf) < buf.index(b"#") + 3:
          chunk = sock.recv(4096)
          if not chunk:
            raise RuntimeError("Connection closed while waiting for halt")

          buf += chunk

      except TimeoutError:
        print("Timed out waiting for halt after interrupt - is the guest still running?")
        break

      finally:
        sock.settimeout(None)

      if b"$" in buf:
        sock.sendall(b"+")



  except KeyboardInterrupt:
    print("\nStopped. Resuming guest.")
    cmd_continue(sock)


if __name__ == "__main__":
  main()
