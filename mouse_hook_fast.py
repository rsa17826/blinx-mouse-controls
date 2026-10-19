#!/usr/bin/env python3
"""Fast mouse-look & virtual gamepad hook: reads real mouse motion and keyboard/mouse
inputs via the IMan filter socket, maintains absolute yaw/pitch state (writing to
xemu guest RAM via /proc/pid/mem), and creates a virtual Xbox gamepad via evdev
to map WASD to the Left Analog Stick and buttons to standard Xbox inputs.

Requires install_asia_mouselook.py to already be installed.

Usage:
    python3 mouse_hook_fast.py <hex_pitch_value_addr> <hex_yaw_value_addr> <ram_host_base>
        [--sensitivity 0.003] [--rate 120] [--invert-y]

"""

import argparse
import math
import os
import struct
import subprocess
import sys
import threading
from evdev import UInput, AbsInfo, ecodes as e

sys.path.insert(0, ".")
from iman_client import FilterConnection, EV_REL, EV_KEY # noqa: E402

PHYS_OFFSET = 0xAF000 # virtual -> physical
RAM_HOST_BASE = int(sys.argv[3], 16)
sys.argv.__delitem__(3)

PIDFILE = "/tmp/virtual_xbox_controller.pid"
FIFO_PATH = "/tmp/virtual_xbox_controller.fifo"

KEY_W = 17
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_E = 18
KEY_Q = 16
KEY_R = 19
KEY_SPACE = 57
KEY_LEFTSHIFT = 42
KEY_LEFTCTRL = 29
KEY_TAB = 15
KEY_ESC = 1
KEY_ENTER = 28
KEY_RIGHTSHIFT = 54

BTN_LEFT = 272
BTN_RIGHT = 273
BTN_MIDDLE = 274

PITCH_MIN = -1.5
PITCH_MAX = 1.5


class FastMemWriter:
  def __init__(self, pid):
    self.fd = open(f"/proc/{pid}/mem", "r+b", buffering=0)

  def write_float(self, virtual_addr, value):
    host_addr = RAM_HOST_BASE + virtual_addr + PHYS_OFFSET
    self.fd.seek(host_addr)
    self.fd.write(struct.pack("<f", value))

  def read_float(self, virtual_addr):
    host_addr = RAM_HOST_BASE + virtual_addr + PHYS_OFFSET
    self.fd.seek(host_addr)
    return struct.unpack("<f", self.fd.read(4))[0]

  def close(self):
    self.fd.close()


def find_xemu_pid():
  out = subprocess.check_output(["pgrep", "-fa", "^xemu"]).decode()
  print(out)
  return int(out.split()[0])


class GamepadClient:
  """Grabs the virtual Xbox gamepad already created by plug_controller.py and
  relays write()/syn() calls to it over its command FIFO. Does not create or
  destroy the underlying device - that's plug_controller.py's / unplug_controller.py's
  job."""

  def __init__(self):
    if not os.path.exists(PIDFILE):
      sys.exit("No virtual controller is plugged in. Run plug_controller.py first.")

    try:
      os.kill(int(open(PIDFILE).read().strip()), 0)

    except ProcessLookupError:
      sys.exit(f"{PIDFILE} points at a dead process. Run unplug_controller.py, then plug_controller.py again.")

    if not os.path.exists(FIFO_PATH):
      sys.exit(f"Controller pidfile exists but {FIFO_PATH} is missing. Run unplug_controller.py, then plug_controller.py again.")

    self.fifo = open(FIFO_PATH, "w")

  def write(self, etype, code, value):
    self.fifo.write(f"{etype} {code} {value}\n")
    self.fifo.flush()

  def syn(self):
    self.write(e.EV_SYN, e.SYN_REPORT, 0)

  def close(self):
    self.fifo.close()


def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("pitch_addr", help="hex address of pitch_value scratch float")
  parser.add_argument("yaw_addr", help="hex address of yaw_value scratch float")
  parser.add_argument("--sensitivity", type=float, default=0.003, help="radians per raw mouse-delta unit")
  parser.add_argument("--rate", type=float, default=120.0, help="max write flush rate in Hz")
  parser.add_argument("--invert-y", action="store_true")
  args = parser.parse_args()
  paused = False
  pitch_addr = int(args.pitch_addr, 16)
  yaw_addr = int(args.yaw_addr, 16)

  pid = find_xemu_pid()
  print(f"xemu PID: {pid}")
  writer = FastMemWriter(pid)
  gamepad = GamepadClient()

  pitch = writer.read_float(pitch_addr)
  yaw = writer.read_float(yaw_addr)
  print(f"Initial pitch (raw, pre-clamp)={pitch:.4f} yaw={yaw:.4f}")

  if abs(pitch) > PITCH_MAX:
    print(f"  (raw pitch {pitch:.4f} is out of the sane range, resetting to 0.0 instead of clamping to an edge)")
    pitch = 0.0
  else:
    pitch = max(PITCH_MIN, min(PITCH_MAX, pitch))

  print(f"Initial pitch (final)={pitch:.4f} yaw={yaw:.4f}")
  writer.write_float(pitch_addr, pitch)

  # Track pressed keys for analog stick calculation
  key_states = {
    KEY_W: False,
    KEY_A: False,
    KEY_S: False,
    KEY_D: False,
  }

  try:
    conn = FilterConnection(
      name="xemu-mouselook-fast",
      keyboards=True,
      mice=True,
      keycodes=[],
    )

  except (ConnectionRefusedError, FileNotFoundError) as err:
    print(f"Could not connect to IMan daemon ({err}) - is it running?")
    sys.exit(1)

  print("Connected to IMan filter socket with Virtual Controller active. Ctrl-C to stop.")

  state_lock = threading.Lock()
  state = {"pitch": pitch, "yaw": yaw, "dirty": False}
  stop_event = threading.Event()
  y_sign = -1.0 if args.invert_y else 1.0
  TWO_PI = 2 * math.pi

  STRAFE_SIGN = 1.0

  def update_left_stick():
    heading_addr = yaw_addr + 12

    side = int(key_states[KEY_D]) - int(key_states[KEY_A])
    fwd = int(key_states[KEY_W]) - int(key_states[KEY_S])

    # When no movement keys are held, center the analog stick completely (0, 0)
    # This frees up the stick so menus work normally.
    if side == 0 and fwd == 0:
      writer.write_float(heading_addr, 0.0)
      gamepad.write(e.EV_ABS, e.ABS_X, 0)
      gamepad.write(e.EV_ABS, e.ABS_Y, 0)
      gamepad.syn()
      return

    # 1. Calculate movement angle relative to the mouse camera view
    movement_angle = math.atan2(STRAFE_SIGN * side, fwd)
    writer.write_float(heading_addr, movement_angle)

    # 2. Map WASD directly to the analog stick axes (lx, ly)
    # A/D -> X axis (-32767 to 32767)
    # W/S -> Y axis (-32767 for forward/W, +32767 for backward/S)
    lx = side * 32767
    ly = -fwd * 32767

    # Normalize diagonal movement vector
    # if lx != 0 and ly != 0:
    #   lx = int(lx * 0.7071)
    #   ly = int(ly * 0.7071)

    gamepad.write(e.EV_ABS, e.ABS_X, lx)
    gamepad.write(e.EV_ABS, e.ABS_Y, ly)
    gamepad.syn()

  def flush_loop():
    interval = 1.0 / args.rate
    while not stop_event.wait(interval):
      with state_lock:
        if not state["dirty"]:
          continue

        p, y = state["pitch"], state["yaw"]
        state["dirty"] = False

      writer.write_float(pitch_addr, p)
      writer.write_float(yaw_addr, y)


  def iman_loop():
    nonlocal paused
    try:
      while not stop_event.is_set():
        ev = conn.read_event()
        block = False
        if ev["type"] == EV_KEY and ev["code"] == 109 and ev["value"] == 1:
          paused = not paused
          conn.block_input(ev["seq"], True)
          continue

        if paused:
          conn.block_input(ev["seq"], False)
          continue

        # Mouse Look Motion
        if ev["type"] == EV_REL:
          if ev["code"] == 0: # REL_X
            with state_lock:
              state["yaw"] += ev["value"] * args.sensitivity
              state["yaw"] = (state["yaw"] + TWO_PI) % TWO_PI
              if state["yaw"] > math.pi:
                state["yaw"] -= TWO_PI

              state["dirty"] = True

            block = True
          elif ev["code"] == 1: # REL_Y
            with state_lock:
              state["pitch"] += y_sign * ev["value"] * args.sensitivity
              state["pitch"] = max(PITCH_MIN, min(PITCH_MAX, state["pitch"]))
              state["dirty"] = True

            block = True


        # Keyboard & Mouse Button Input
        elif ev["type"] == EV_KEY:
          code = ev["code"]
          pressed = bool(ev["value"])

          # WASD -> Left Stick
          if code in key_states:
            key_states[code] = pressed
            update_left_stick()
            block = True

          # LButton -> Controller X
          elif code == BTN_LEFT:
            gamepad.write(e.EV_KEY, e.BTN_NORTH, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Space -> Controller A
          elif code == KEY_SPACE:
            gamepad.write(e.EV_KEY, e.BTN_SOUTH, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # RButton -> Controller B
          elif code == BTN_RIGHT:
            gamepad.write(e.EV_KEY, e.BTN_EAST, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # E Key -> Controller Y
          elif code == KEY_E:
            gamepad.write(e.EV_KEY, e.BTN_WEST, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Q Key -> Left Bumper (LB)
          elif code == KEY_Q:
            gamepad.write(e.EV_KEY, e.BTN_TL, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Middle Mouse / R Key -> Right Bumper (RB)
          elif code in (BTN_MIDDLE, KEY_R):
            gamepad.write(e.EV_KEY, e.BTN_TR, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Left Shift -> Left Trigger (LT / Aim)
          elif code == KEY_LEFTSHIFT:
            gamepad.write(e.EV_ABS, e.ABS_Z, 255 if pressed else 0)
            gamepad.syn()
            block = True

          # Right Shift -> Right Trigger (RT / Shoot)
          elif code == KEY_RIGHTSHIFT:
            gamepad.write(e.EV_ABS, e.ABS_RZ, 255 if pressed else 0)
            gamepad.syn()
            block = True

          # Left Control -> L3 (Left Stick Click)
          elif code == KEY_LEFTCTRL:
            gamepad.write(e.EV_KEY, e.BTN_THUMBL, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Tab -> Back / Select
          elif code == KEY_TAB:
            gamepad.write(e.EV_KEY, e.BTN_SELECT, 1 if pressed else 0)
            gamepad.syn()
            block = True
          elif code == KEY_ENTER:
            gamepad.write(e.EV_KEY, e.BTN_START, 1 if pressed else 0)
            gamepad.syn()
            block = True


          # print(code)

        conn.block_input(ev["seq"], block)


    except ConnectionError as err:
      print(f"IMan connection lost: {err}")
      stop_event.set()


  flush_thread = threading.Thread(target=flush_loop, daemon=True)
  iman_thread = threading.Thread(target=iman_loop, daemon=True)
  flush_thread.start()
  iman_thread.start()

  try:
    while not stop_event.is_set():
      stop_event.wait(0.5)


  except KeyboardInterrupt:
    print("\nStopped.")

  finally:
    stop_event.set()
    flush_thread.join(timeout=2)
    conn.close()
    gamepad.close()
    writer.close()


if __name__ == "__main__":
  main()
