"""Unplugs the virtual Xbox gamepad started by plug_controller.py.

Usage:
    python3 unplug_controller.py

"""

import os
import signal
import sys
import time

PIDFILE = "/tmp/virtual_xbox_controller.pid"


def main():
  if not os.path.exists(PIDFILE):
    sys.exit("No controller is plugged in (no pidfile found at " + PIDFILE + ").")

  pid = int(open(PIDFILE).read().strip())

  try:
    os.kill(pid, signal.SIGTERM)

  except ProcessLookupError:
    os.remove(PIDFILE)
    sys.exit(f"pidfile pointed at pid {pid}, but that process was already gone. Removed the stale pidfile.")

  for _ in range(10):
    if not os.path.exists(PIDFILE):
      print("Controller unplugged.")
      return

    time.sleep(0.1)

  try:
    os.kill(pid, signal.SIGKILL)
    os.remove(PIDFILE)

  except ProcessLookupError:
    os.remove(PIDFILE)
    sys.exit(f"pidfile pointed at pid {pid}, but that process was already gone. Removed the stale pidfile.")

  sys.exit(f"Sent SIGTERM to pid {pid} but it hasn't cleaned up after 5s - check on it manually.")


if __name__ == "__main__":
  main()
