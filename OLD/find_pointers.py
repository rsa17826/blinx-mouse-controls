import struct

target_va = 0x0171c694
needle = struct.pack("<I", target_va)
xbe_path = "Blinx - The Time Sweeper (Asia) (En,Ja).xiso/default.xbe"

with open(xbe_path, "rb") as f:
    data = f.read()

idx = 0
while True:
    idx = data.find(needle, idx)
    if idx == -1:
        break
    print(f"Found pointer to VA 0x{target_va:08x} at file offset 0x{idx:08x}")
    idx += 1
