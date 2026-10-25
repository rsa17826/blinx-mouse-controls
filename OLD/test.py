import sys, struct

sys.path.insert(0, "lib")
from gdb_rsp import connect, set_watchpoint, remove_watchpoint, send_packet, wait_for_stop, read_all_registers, readf, cmd_continue

LAST = 0x141FC9
MEM = {"yaw": 0x141FB9, "pi": 0x141FBD, "hoff": 0x141FC5, "last": LAST, "heading": 0x4EAAAC}


def ext80(raw):
  mant = int.from_bytes(raw[:8], "little")
  se = int.from_bytes(raw[8:10], "little")
  exp = se & 0x7FFF
  if exp == 0x7FFF:
    return float("nan")

  if mant == 0:
    return 0.0

  sign = -1.0 if se & 0x8000 else 1.0
  return sign * mant / 2**63 * 2.0 ** (exp - 16383)


sock = connect()
set_watchpoint(sock, LAST, 4)
try:
  for _ in range(5):
    send_packet(sock, b"c")
    wait_for_stop(sock)
    blob = bytes.fromhex(read_all_registers(sock))
    eip = int.from_bytes(blob[32:36], "little")
    st = [ext80(blob[64 + 10 * i : 74 + 10 * i]) for i in range(8)]
    fstat, ftag = struct.unpack("<II", blob[148:156])
    mem = {k: readf(sock, a) for k, a in MEM.items()}
    top = (fstat >> 11) & 7
    lg = [st[(top + i) & 7] for i in range(8)]
    mem = {k: readf(sock, a) for k, a in MEM.items()}
    print(f"eip={eip:#x} top={top} st0={lg[0]:+.4f} st1={lg[1]:+.4f} st2={lg[2]:+.4f} phys={[round(x, 3) for x in st]}")

    print("   mem: " + " ".join(f"{k}={v:+.4f}" for k, v in mem.items()))


finally:
  remove_watchpoint(sock, LAST, 4)
  cmd_continue(sock)
