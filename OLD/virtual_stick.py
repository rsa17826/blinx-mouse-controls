#!/usr/bin/env python3
"""Create a virtual gamepad (via uinput) whose RIGHT STICK tracks mouse
movement, LEFT STICK tracks WASD (digital, full deflection while a key
is held), and face/shoulder buttons map to configurable keyboard/mouse
buttons - all so xemu sees one complete, ordinary-looking gamepad.

Real mouse/keyboard events are read via the IMan filter-mode socket
(see iman_client.py / inputevents.go), NOT raw evdev - this lets us
explicitly BLOCK every event we consume from reaching anything else
(the real desktop/game window), which fixes the double-input problem
you get from reading evdev directly (the OS still delivers those same
events to whatever has focus, so the game saw both the real mouse
motion AND our synthetic gamepad at once).

Because a joystick axis is a POSITION (not a velocity/delta like mouse
movement), the right stick uses "spring-centering": each mouse-move
event nudges it towards deflection proportional to recent mouse speed,
and a background thread decays it back toward center when you stop
moving the mouse - approximating holding a stick over while turning,
releasing as you stop.

Requires:
    pip install evdev --break-system-packages
    Read/write access to /dev/uinput (run as root, or set up a udev
    rule - see NOTES at the bottom).
    The IMan daemon must already be running and listening on
    /tmp/kbd_manager.sock.

Usage:
    python3 virtual_stick.py [--sensitivity 3200] [--decay 8.0]
        [--rate 125] [--invert-y]

Edit KEY_MAP and WASD_KEYS below to change which keys do what.

After running this, configure xemu to use the new virtual device
("xemu-mouselook-virtual-gamepad") as Player 1's controller. Most
emulators only enumerate joysticks at startup - if it doesn't show up,
start this script FIRST, then (re)start xemu.
"""

import argparse
import sys
import threading
import time

try:
  import evdev
  from evdev import ecodes, UInput, AbsInfo

except ImportError:
  print("evdev not installed. Run:")
  print("  pip install evdev --break-system-packages")
  sys.exit(1)

sys.path.insert(0, ".")
from iman_client import FilterConnection, EV_KEY, EV_REL # noqa: E402

AXIS_MIN = -32768
AXIS_MAX = 32767
AXIS_RANGE = AXIS_MAX # symmetric enough for our purposes

# Standard evdev codes for mouse relative axes and buttons (used when
# matching events read via IMan, same numeric values as ecodes.*).
REL_X = ecodes.REL_X
REL_Y = ecodes.REL_Y

# --- Configure your bindings here ---

# WASD -> left stick, digital (full deflection while held). Edit the
# evdev key codes on the left if you want different movement keys.
WASD_KEYS = {
  ecodes.KEY_W: ("y", -1.0),
  ecodes.KEY_S: ("y", +1.0),
  ecodes.KEY_A: ("x", -1.0),
  ecodes.KEY_D: ("x", +1.0),
}

KEY_MAP = {
  ecodes.KEY_SPACE: ecodes.BTN_A,
  ecodes.KEY_E: ecodes.BTN_Y,
  ecodes.KEY_Q: ecodes.BTN_TL,
  ecodes.KEY_R: ecodes.BTN_TR,
  ecodes.KEY_TAB: ecodes.BTN_SELECT,
  ecodes.KEY_ENTER: ecodes.BTN_START,
  ecodes.KEY_C: ecodes.BTN_THUMBL,
  ecodes.KEY_ENTER: ecodes.BTN_TR2,
  ecodes.KEY_ESC: ecodes.BTN_TL2,
}

# Mouse buttons -> gamepad buttons (read from the mouse device, not
# the keyboard device).
MOUSE_BUTTON_MAP = {
  ecodes.BTN_LEFT: ecodes.BTN_X,
  ecodes.BTN_RIGHT: ecodes.BTN_B,
}
# --- End configuration ---


def make_virtual_gamepad():
  """Create a uinput device with two analog sticks and the standard
  face/shoulder/trigger buttons referenced by KEY_MAP/MOUSE_BUTTON_MAP
  above, so xemu's input backend recognizes it as a full gamepad."""
  abs_info = AbsInfo(value=0, min=AXIS_MIN, max=AXIS_MAX, fuzz=16, flat=128, resolution=0)
  trigger_info = AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)
  capabilities = {
    ecodes.EV_ABS: [
      (ecodes.ABS_X, abs_info),
      (ecodes.ABS_Y, abs_info),
      (ecodes.ABS_RX, abs_info),
      (ecodes.ABS_RY, abs_info),
      (ecodes.ABS_Z, trigger_info),
      (ecodes.ABS_RZ, trigger_info),
    ],
    ecodes.EV_KEY: sorted(set([ecodes.BTN_A, ecodes.BTN_B, ecodes.BTN_X, ecodes.BTN_Y, ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_TL2, ecodes.BTN_TR2, ecodes.BTN_SELECT, ecodes.BTN_START, ecodes.BTN_THUMBL, ecodes.BTN_THUMBR, ecodes.BTN_GAMEPAD] + list(KEY_MAP.values()) + list(MOUSE_BUTTON_MAP.values()))),
  }
  return UInput(capabilities, name="xemu-mouselook-virtual-gamepad")


def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--sensitivity", type=float, default=3200.0, help="mouse units for full stick deflection (default 3200)")
  parser.add_argument("--decay", type=float, default=8.0, help="spring-back rate per second (default 8.0)")
  parser.add_argument("--rate", type=float, default=125.0, help="decay/update tick rate in Hz (default 125)")
  parser.add_argument("--invert-y", action="store_true")
  args = parser.parse_args()

  try:
    gamepad = make_virtual_gamepad()

  except PermissionError:
    print("Permission denied creating /dev/uinput device. Run as root, or set up a udev rule (see script docstring / NOTES).")
    sys.exit(1)

  print(f"Virtual gamepad created: {gamepad.device.path}")
  print("Point xemu's controller settings at this device (may show up as 'xemu-mouselook-virtual-gamepad'). If it doesn't appear, restart xemu with this script already running.")
  print(f"sensitivity={args.sensitivity} decay={args.decay} rate={args.rate}Hz")

  # Only subscribe to the exact keyboard keys we map, plus ALL mouse
  # events (motion needs the Mice device-type flag since REL_X/REL_Y
  # aren't "keycodes"; mouse buttons happen to also be caught by the
  # Mice flag as their originating device is the mouse). We deliberately
  # do NOT set keyboards=True, which would forward every keystroke on
  # the system to us for a block decision - unnecessary overhead and
  # risk for keys we don't care about.
  subscribed_keycodes = list(WASD_KEYS.keys()) + list(KEY_MAP.keys())
  try:
    conn = FilterConnection(
      name="xemu-mouselook",
      keyboards=False,
      mice=True,
      keycodes=subscribed_keycodes,
    )

  except (ConnectionRefusedError, FileNotFoundError) as e:
    print(f"Could not connect to IMan daemon at /tmp/kbd_manager.sock ({e}) - is it running?")
    sys.exit(1)

  print("Connected to IMan filter socket. Ctrl-C to stop.")

  state_lock = threading.Lock()
  axis = {"x": 0.0, "y": 0.0} # right-stick deflection, -1.0..1.0
  wasd_state = {"x": 0.0, "y": 0.0} # left-stick digital deflection
  pressed_wasd = set()
  stop_event = threading.Event()
  y_sign = -1.0 if args.invert_y else 1.0

  def write_left_stick():
    with state_lock:
      x_val = int(wasd_state["x"] * AXIS_RANGE)
      y_val = int(wasd_state["y"] * AXIS_RANGE)

    gamepad.write(ecodes.EV_ABS, ecodes.ABS_X, x_val)
    gamepad.write(ecodes.EV_ABS, ecodes.ABS_Y, y_val)
    gamepad.syn()

  def recompute_wasd_axis():
    x = 0.0
    y = 0.0
    for key, (axis_name, direction) in WASD_KEYS.items():
      if key in pressed_wasd:
        if axis_name == "x":
          x += direction
        else:
          y += direction



    wasd_state["x"] = max(-1.0, min(1.0, x))
    wasd_state["y"] = max(-1.0, min(1.0, y))

  def decay_loop():
    interval = 1.0 / args.rate
    decay_factor_per_tick = max(0.0, 1.0 - args.decay * interval)
    while not stop_event.wait(interval):
      with state_lock:
        axis["x"] *= decay_factor_per_tick
        axis["y"] *= decay_factor_per_tick
        x_val = int(max(-1.0, min(1.0, axis["x"])) * AXIS_RANGE)
        y_val = int(max(-1.0, min(1.0, axis["y"])) * AXIS_RANGE)

      gamepad.write(ecodes.EV_ABS, ecodes.ABS_RX, x_val)
      gamepad.write(ecodes.EV_ABS, ecodes.ABS_RY, y_val)
      gamepad.syn()


  def iman_loop():
    try:
      while not stop_event.is_set():
        ev = conn.read_event()
        block = False

        if ev["type"] == EV_REL:
          if ev["code"] == REL_X:
            with state_lock:
              axis["x"] += ev["value"] / args.sensitivity
              axis["x"] = max(-1.0, min(1.0, axis["x"]))

            block = True
          elif ev["code"] == REL_Y:
            with state_lock:
              axis["y"] += (y_sign * ev["value"]) / args.sensitivity
              axis["y"] = max(-1.0, min(1.0, axis["y"]))

            block = True

        elif ev["type"] == EV_KEY:
          code = ev["code"]
          value = ev["value"] # 1=press, 0=release, 2=autorepeat

          if code in MOUSE_BUTTON_MAP:
            if value in (0, 1):
              gamepad.write(ecodes.EV_KEY, MOUSE_BUTTON_MAP[code], value)
              gamepad.syn()

            block = True

          elif code in WASD_KEYS:
            if value == 1:
              pressed_wasd.add(code)
              recompute_wasd_axis()
              write_left_stick()
            elif value == 0:
              pressed_wasd.discard(code)
              recompute_wasd_axis()
              write_left_stick()

            block = True

          elif code in KEY_MAP:
            if value in (0, 1):
              gamepad.write(ecodes.EV_KEY, KEY_MAP[code], value)
              gamepad.syn()

            block = True


        conn.block_input(ev["seq"], block)


    except ConnectionError as e:
      print(f"IMan connection lost: {e}")
      stop_event.set()


  decay_thread = threading.Thread(target=decay_loop, daemon=True)
  iman_thread = threading.Thread(target=iman_loop, daemon=True)
  decay_thread.start()
  iman_thread.start()

  try:
    while not stop_event.is_set():
      time.sleep(0.5)


  except KeyboardInterrupt:
    print("\nStopped.")

  finally:
    stop_event.set()
    decay_thread.join(timeout=2)
    conn.close()
    gamepad.close()


if __name__ == "__main__":
  main()

# NOTES on /dev/uinput permissions (NixOS and general Linux):
#
# If you don't want to run this as root every time, add a udev rule
# granting your user's group access to /dev/uinput, e.g. on most
# distros: create /etc/udev/rules.d/99-uinput.rules containing:
#
#     KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
#
# then add yourself to the 'input' group and reload udev rules
# (or just reboot). On NixOS specifically, this usually needs to be
# done via services.udev.extraRules in configuration.nix rather than
# editing /etc directly, since /etc is managed declaratively.
