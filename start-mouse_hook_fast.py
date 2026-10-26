#!/usr/bin/env python3
"""Fast mouse-look & virtual gamepad hook: reads real mouse motion and keyboard/mouse
inputs via the IMan filter socket, maintains absolute yaw/pitch state (writing to
xemu guest RAM via /proc/pid/mem), and creates a virtual Xbox gamepad via evdev
to map WASD to the Left Analog Stick and buttons to standard Xbox inputs.

Requires install_asia_mouselook.py to already be installed.

Usage:
    python3 mouse_hook_fast.py <hex_pitch_value_addr> <hex_yaw_value_addr>
        [--sensitivity 0.003] [--rate 120] [--invert-y]

"""

import time
import subprocess
import argparse
import math
import os
import struct
import sys
import threading

sys.path.insert(0, ".")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "./lib")))
from iman_client import FilterConnection
from fastmem import FastMemWriter # noqa: E402

PIDFILE = "/tmp/virtual_xbox_controller.pid"
FIFO_PATH = "/tmp/virtual_xbox_controller.fifo"

import keymap as km

PITCH_MIN = -1.5
PITCH_MAX = 1.5

# When the byte at RESET_WATCH_ADDR changes to RESET_WATCH_VALUE, the view is reset to pitch 0 / yaw 0.
# 89 is when in level
RESET_WATCH_ADDR = 0xF05B987C
RESET_WATCH_VALUE = 0x89


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
    self.write(km.EV_SYN, km.SYN_REPORT, 0)

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
  paused = True
  pitch_addr = int(args.pitch_addr, 16)
  yaw_addr = int(args.yaw_addr, 16)

  writer = FastMemWriter()
  print(f"xemu PID: {writer.pid}  RAM base: 0x{writer.ram_base:x}")
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

  # Track pressed km.keys for analog stick calculation
  key_states = {
    km.KEY_W: False,
    km.KEY_A: False,
    km.KEY_S: False,
    km.KEY_D: False,
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
  storedangle = {"pitch": 0.3240000000000002, "yaw": -2.5331853071795454}
  stop_event = threading.Event()
  y_sign = -1.0 if args.invert_y else 1.0
  TWO_PI = 2 * math.pi

  STRAFE_SIGN = 1.0

  def update_left_stick():
    heading_addr = yaw_addr + 12

    side = int(key_states[km.KEY_D]) - int(key_states[km.KEY_A])
    fwd = int(key_states[km.KEY_W]) - int(key_states[km.KEY_S])

    # When no movement keys are held, center the analog stick completely (0, 0)
    # This frees up the stick so menus work normally.
    if side == 0 and fwd == 0:
      writer.write_float(heading_addr, 0.0)
      gamepad.write(km.EV_ABS, km.ABS_X, 0)
      gamepad.write(km.EV_ABS, km.ABS_Y, 0)
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

    gamepad.write(km.EV_ABS, km.ABS_X, lx)
    gamepad.write(km.EV_ABS, km.ABS_Y, ly)
    gamepad.syn()

  def flush_loop():
    interval = 1.0 / args.rate
    last_watch = writer.read(RESET_WATCH_ADDR, 1)[0]
    while not stop_event.wait(interval):
      watch = writer.read(RESET_WATCH_ADDR, 1)[0]
      if watch == RESET_WATCH_VALUE and last_watch != RESET_WATCH_VALUE:
        with state_lock:
          state["pitch"], state["yaw"] = storedangle["pitch"], storedangle["yaw"]
          state["dirty"] = True


      last_watch = watch

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
        if ev["type"] == km.EV_KEY and ev["code"] == km.KEY_PAGEDOWN and ev["value"] == 1:
          paused = not paused
          conn.block_input(ev["seq"], True)
          continue

        if paused:
          conn.block_input(ev["seq"], False)
          continue

        # Mouse Look Motion
        if ev["type"] == km.EV_REL:
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
        elif ev["type"] == km.EV_KEY:
          code = ev["code"]
          pressed = bool(ev["value"])

          # WASD -> Left Stick
          if code in key_states:
            key_states[code] = pressed
            update_left_stick()
            block = True

          elif code == km.KEY_KP7:
            subprocess.Popen(args=["./call/il_superbomb"], executable="./call/il_superbomb")
          elif code == km.KEY_KP9:
            storedangle["pitch"], storedangle["yaw"] = state["pitch"], state["yaw"]
            print(f'\n\nstoredangle = {"{"}"pitch": {storedangle["pitch"]}, "yaw": {storedangle["yaw"]}{"}"}\n\n')

          # LButton -> Controller X
          elif code == km.BTN_LEFT:
            if pressed:
              btn_left_press_time = time.time()
              gamepad.write(km.EV_KEY, km.BTN_NORTH, 1)
              gamepad.syn()
            else:
              elapsed = time.time() - btn_left_press_time
              min_duration = 0.1 # 100ms

              if elapsed < min_duration:
                # If released too fast, delay the release in a background thread to fulfill the 100ms minimum
                remaining = min_duration - elapsed

                def delayed_release():
                  time.sleep(remaining)
                  gamepad.write(km.EV_KEY, km.BTN_NORTH, 0)
                  gamepad.syn()

                threading.Thread(target=delayed_release, daemon=True).start()
              else:
                # If held longer than 100ms, release immediately when the physical button goes up
                gamepad.write(km.EV_KEY, km.BTN_NORTH, 0)
                gamepad.syn()


            # gamepad.write(km.EV_KEY, km.BTN_NORTH, 1 if pressed else 0)
            # gamepad.syn()
            block = True

          # Space -> Controller A
          elif code == km.KEY_SPACE:
            gamepad.write(km.EV_KEY, km.BTN_SOUTH, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # RButton -> Controller B
          elif code == km.BTN_RIGHT:
            gamepad.write(km.EV_KEY, km.BTN_EAST, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # E Key -> Controller Y
          elif code == km.KEY_E:
            gamepad.write(km.EV_KEY, km.BTN_WEST, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Q Key -> Left Bumper (LB)
          elif code == km.KEY_Q:
            gamepad.write(km.EV_KEY, km.BTN_TL, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Middle Mouse / R Key -> Right Bumper (RB)
          elif code in (km.BTN_MIDDLE, km.KEY_R):
            gamepad.write(km.EV_KEY, km.BTN_TR, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Left Shift -> Left Trigger (LT / Aim)
          elif code == km.KEY_LEFTSHIFT:
            gamepad.write(km.EV_ABS, km.ABS_Z, 255 if pressed else 0)
            gamepad.syn()
            block = True

          # Right Shift -> Right Trigger (RT / Shoot)
          elif code == km.KEY_RIGHTSHIFT:
            gamepad.write(km.EV_ABS, km.ABS_RZ, 255 if pressed else 0)
            gamepad.syn()
            block = True

          # Left Control -> L3 (Left Stick Click)
          elif code == km.KEY_LEFTCTRL:
            gamepad.write(km.EV_KEY, km.BTN_THUMBL, 1 if pressed else 0)
            gamepad.syn()
            block = True

          # Tab -> Back / Select
          elif code == km.KEY_TAB:
            gamepad.write(km.EV_KEY, km.BTN_SELECT, 1 if pressed else 0)
            gamepad.syn()
            block = True
          elif code == km.KEY_ENTER:
            gamepad.write(km.EV_KEY, km.BTN_START, 1 if pressed else 0)
            gamepad.syn()
            block = True


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
