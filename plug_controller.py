"""Creates the virtual Xbox gamepad device and keeps it alive, relaying
gamepad write/syn commands sent over a FIFO by other scripts (e.g.
mouse_hook_fast.py). Run this once before starting mouse_hook_fast.py.
Run unplug_controller.py to tear the device down again.

Usage:
    python3 plug_controller.py
    python3 plug_controller.py &

"""

import os
import signal
import sys
from evdev import UInput, AbsInfo, ecodes as e

PIDFILE = "/tmp/virtual_xbox_controller.pid"
FIFO_PATH = "/tmp/virtual_xbox_controller.fifo"

stop = False


def handle_signal(signum, frame):
  global stop
  stop = True


def setup_virtual_gamepad():
  capabilities = {
    e.EV_KEY: [
      e.BTN_SOUTH,
      e.BTN_EAST,
      e.BTN_WEST,
      e.BTN_NORTH,
      e.BTN_TL,
      e.BTN_TR,
      e.BTN_SELECT,
      e.BTN_START,
      e.BTN_THUMBL,
      e.BTN_THUMBR,
    ],
    e.EV_ABS: [
      (e.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
      (e.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
      (e.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
      (e.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
      (e.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
      (e.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
    ],
  }
  return UInput(capabilities, name="Virtual Xbox Controller")


def main():
  if os.path.exists(PIDFILE):
    old_pid = int(open(PIDFILE).read().strip())
    try:
      os.kill(old_pid, 0)

    except ProcessLookupError:
      os.remove(PIDFILE)
    else:
      sys.exit(f"Controller is already plugged in (pid {old_pid}). Run unplug_controller.py first.")


  if os.path.exists(FIFO_PATH):
    os.remove(FIFO_PATH)

  os.mkfifo(FIFO_PATH)

  gamepad = setup_virtual_gamepad()
  print(f"Virtual Xbox Controller plugged in at {gamepad.device.path}")

  with open(PIDFILE, "w") as f:
    f.write(str(os.getpid()))

  signal.signal(signal.SIGTERM, handle_signal)
  signal.signal(signal.SIGINT, handle_signal)

  print(f"Listening for gamepad commands on {FIFO_PATH} - Ctrl-C or unplug_controller.py to stop.")

  try:
    while not stop:
      with open(FIFO_PATH, "r") as fifo:
        for line in fifo:
          if stop:
            break

          parts = line.split()
          if len(parts) != 3:
            print(f"Malformed command on FIFO, ignoring: {line!r}")
            continue

          etype, code, value = (int(p) for p in parts)
          gamepad.write(etype, code, value)




  finally:
    gamepad.close()
    if os.path.exists(FIFO_PATH):
      os.remove(FIFO_PATH)

    if os.path.exists(PIDFILE):
      os.remove(PIDFILE)

    print("Controller unplugged.")


if __name__ == "__main__":
  main()
