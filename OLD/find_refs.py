import struct

# The virtual addresses found in your previous scan
target_vas = [0x0171C694, 0x017990CC]

xbe_path = "Blinx - The Time Sweeper (Asia) (En,Ja).xiso/default.xbe"

with open(xbe_path, "rb") as f:
  data = f.read()

for va in target_vas:
  # Convert VA to 4-byte little-endian bytes (e.g., 0x0171c694 -> \x94\xc6\x71\x01)
  needle = struct.pack("<I", va)
  idx = 0
  while True:
    idx = data.find(needle, idx)
    if idx == -1:
      break

    print(f"Found reference to VA 0x{va:08x} at file offset 0x{idx:08x}")
    idx += 1

