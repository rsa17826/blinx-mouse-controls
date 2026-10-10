import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory, cmd_continue
import time

CANDIDATES = [
  0x00141EE5,
  0x001424D0,
  0x0014268C,
  0x00142BD0,
  0x001436E4,
  0x00175150,
  0x00175A43,
  0x001D2E7C,
  0x001D3235,
  0x001D797C,
  0x001D80E4,
  0x001D8498,
  0x001D884C,
  0x001D8C00,
]


def safe_read(addr, length, retries=5):
  for attempt in range(retries):
    try:
      sock = connect()
      data = read_memory(sock, addr, length)
      cmd_continue(sock)
      return data

    except (ValueError, RuntimeError, ConnectionError) as e:
      print(f"  (transient read error at 0x{addr:x}, retry {attempt + 1}/{retries}: {e})")
      time.sleep(0.1)


  raise RuntimeError(f"Failed to read 0x{addr:x} after {retries} retries")


print("Move around / play actively for the next ~10 seconds while this checks stability...")
baseline = {addr: safe_read(addr, 64) for addr in CANDIDATES}

unstable = set()
for i in range(20):
  time.sleep(0.5)
  for addr in CANDIDATES:
    if addr in unstable:
      continue

    current = safe_read(addr, 64)
    if current != baseline[addr]:
      print(f"UNSTABLE: 0x{addr:08x} changed at t={i * 0.5:.1f}s (was {baseline[addr][:8].hex()}, now {current[:8].hex()})")
      unstable.add(addr)



print(f"\nDone. {len(CANDIDATES) - len(unstable)}/{len(CANDIDATES)} stayed stable:")
for addr in CANDIDATES:
  if addr not in unstable:
    print(f"  0x{addr:08x}  <- SAFE candidate")

