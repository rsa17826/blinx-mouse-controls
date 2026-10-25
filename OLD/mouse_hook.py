#!/usr/bin/env python3
import argparse
import struct
import sys
import os

try:
  import evdev
  from evdev import ecodes

except ImportError:
  print("evdev not installed. Run: pip install evdev --break-system-packages")
  sys.exit(1)


def find_xemu_ram_base(pid):
  """
  Parse /proc/[pid]/maps to find where xemu mapped the Xbox guest RAM.
  Xemu typically allocates a single 128MB (0x8000000) or 64MB (0x4000000)
  read/write block for this.
  """
  try:
    with open(f"/proc/{pid}/maps", "r") as f:
      for line in f:
        parts = line.split()
        if len(parts) < 2:
          continue

        # Must be read/write memory
        if not parts[1].startswith("rw"):
          continue

        start_str, end_str = parts[0].split("-")
        start = int(start_str, 16)
        end = int(end_str, 16)
        size = end - start

        # Check for 128MB or 64MB chunk
        if size == 0x8000000 or size == 0x4000000:
          return start




  except PermissionError:
    print("Permission denied reading maps. Try running with sudo.")
    sys.exit(1)

  except FileNotFoundError:
    print(f"Process {pid} not found.")
    sys.exit(1)

  return None


def read_mem(fd, address, size=4):
  """Directly read memory from the process without halting it."""
  return os.pread(fd, size, address)


def write_mem(fd, address, data):
  """Directly write memory to the process without halting it."""
  os.pwrite(fd, data, address)


def add_to_scratch_float(fd, addr, delta):
  """Read-modify-write a float in process memory instantly."""
  raw = read_mem(fd, addr, 4)
  current = struct.unpack("<f", raw)[0]
  new_value = current + delta
  print(new_value)
  write_mem(fd, addr, struct.pack("<f", new_value))


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("pid", type=int, help="Process ID of the game")
  parser.add_argument("yaw_addr", help="hex guest address of yaw_delta")
  parser.add_argument("pitch_addr", help="hex guest address of pitch_delta")
  parser.add_argument("--device", default=None, help="evdev device path")
  parser.add_argument("--sensitivity", type=float, default=0.003)
  parser.add_argument("--invert-y", action="store_true")
  args = parser.parse_args()

  guest_yaw = int(args.yaw_addr, 16)
  guest_pitch = int(args.pitch_addr, 16)

  # 1. Translate Guest Addresses to Host Addresses
  ram_base = find_xemu_ram_base(args.pid)
  if not ram_base:
    print("Could not find xemu guest RAM allocation (looked for 64MB/128MB block).")
    sys.exit(1)

  host_yaw = ram_base + guest_yaw
  host_pitch = ram_base + guest_pitch

  print(f"Found xemu RAM base at: 0x{ram_base:016x}")
  print(f"Translated Yaw:   0x{guest_yaw:08x} -> 0x{host_yaw:016x}")
  print(f"Translated Pitch: 0x{guest_pitch:08x} -> 0x{host_pitch:016x}")

  # 2. Device Selection
  if args.device:
    device = evdev.InputDevice(args.device)
  else:
    candidates = [evdev.InputDevice(p) for p in evdev.list_devices()]
    mice = [d for d in candidates if ecodes.EV_REL in d.capabilities()]
    if not mice:
      print("No mouse devices found.")
      sys.exit(1)

    device = mice[0]
    print(f"Auto-selected device: {device.path} ({device.name})")

  y_sign = -1.0 if args.invert_y else 1.0

  # 3. Open the memory file descriptor for direct access
  mem_path = f"/proc/{args.pid}/mem"
  try:
    mem_fd = os.open(mem_path, os.O_RDWR)

  except PermissionError:
    print(f"Permission denied accessing {mem_path}. Run as root (sudo).")
    sys.exit(1)

  print("Hooking mouse via DMA... Ctrl-C to stop.")

  # 4. Input Loop
  try:
    for event in device.read_loop():
      if event.type != ecodes.EV_REL:
        continue

      if event.code == ecodes.REL_X:
        add_to_scratch_float(mem_fd, host_yaw, event.value * args.sensitivity)
      elif event.code == ecodes.REL_Y:
        add_to_scratch_float(mem_fd, host_pitch, y_sign * event.value * args.sensitivity)



  except KeyboardInterrupt:
    print("\nStopped.")

  except OSError as e:
    print(f"\nOS Error (Game probably closed): {e}")

  finally:
    os.close(mem_fd)


if __name__ == "__main__":
  main()
