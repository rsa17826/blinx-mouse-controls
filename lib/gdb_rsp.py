#!/usr/bin/env python3
"""Minimal GDB Remote Serial Protocol client - read/write guest memory
directly, without depending on the full `gdb` client (which choked on
RLE-encoded replies from this xemu/QEMU build).

Requires xemu launched with the gdbstub enabled and NOT halted, e.g.:
    xemu -s -qmp tcp:localhost:4444,server,nowait ...
  (note: -s only, no -S, so the game boots and runs normally while the
  stub is still available to connect to)

IMPORTANT: addresses here are interpreted by the CPU as VIRTUAL
addresses (post-paging), not the physical offsets you got from
pmemsave/ram_diff.py. You must translate first - see verify_translation().

Usage:
    python3 gdb_rsp.py read <hex_addr> <num_bytes>
    python3 gdb_rsp.py write <hex_addr> <hex_bytes>
    python3 gdb_rsp.py read32 <hex_addr>
    python3 gdb_rsp.py write32 <hex_addr> <decimal_value>
    python3 gdb_rsp.py verify <physical_hex_addr> <expected_hex_byte> <base_offset_hex>
    python3 gdb_rsp.py continue
    python3 gdb_rsp.py detach
    python3 gdb_rsp.py scan <snapshot_path> <physical_hex_addr> <sig_len> <start_hex> <end_hex>
    python3 gdb_rsp.py watch <virtual_hex_addr> <length_decimal> [num_hits]

"""

import socket
import sys

HOST = "localhost"
PORT = 1234


def checksum(data: bytes) -> str:
  return format(sum(data) % 256, "02x")


def send_packet(sock, data: bytes):
  packet = b"$" + data + b"#" + checksum(data).encode()
  sock.sendall(packet)


def recv_ack_or_packet(sock):
  """Read the first byte. If it's '+', consume it as an ack and read
  the following reply packet normally. If it's '$', the server is in
  no-ack mode and this IS the reply packet already - handle it as such
  without expecting a separate ack."""
  first = sock.recv(1)
  if first == b"+":
    return recv_packet(sock)
  elif first == b"$":
    return recv_packet(sock, leading_dollar_consumed=True)
  else:
    raise RuntimeError(f"Unexpected first byte, got {first!r}")


def recv_packet(sock, leading_dollar_consumed=False):
  # Read until we see a full $...#xx packet, ack it, return the payload.
  buf = b"$" if leading_dollar_consumed else b""
  while b"#" not in buf or len(buf) < buf.index(b"#") + 3:
    chunk = sock.recv(4096)
    if not chunk:
      raise RuntimeError("Connection closed while waiting for packet")

    buf += chunk
  start = buf.index(b"$")
  end = buf.index(b"#", start)
  payload = buf[start + 1 : end]
  sock.sendall(b"+") # ack it (harmless even in no-ack mode)
  return payload


def connect():
  sock = socket.create_connection((HOST, PORT))
  # QEMU's gdbstub sends an unsolicited stop-notification packet the
  # moment a new debugger connection attaches (since attaching halts
  # the guest CPU). Drain and discard it here so it doesn't get
  # mistaken for the reply to our first real command.
  sock.settimeout(0.3)
  try:
    leftover = sock.recv(4096)
    if leftover:
      # ack it in case it was a full packet expecting one
      sock.sendall(b"+")


  except socket.timeout:
    pass

  sock.settimeout(None)
  return sock


def query_max_packet_size(sock, default=0x1000, safety_margin=64):
  """Negotiate with the gdbstub via qSupported to find its real max
  packet size, so we can safely use larger read chunks than the
  conservative 0x1000 default without triggering False 'faults' from
  oversized requests being rejected.

  Returns a safe chunk size in RAW BYTES (i.e. already accounting for
  the 2x hex-encoding blowup and packet framing overhead), or `default`
  if negotiation fails or doesn't report a PacketSize.
  """
  try:
    send_packet(sock, b"qSupported:multiprocess+;swbreak+;hwbreak+")
    payload = recv_ack_or_packet(sock)

  except Exception as e:
    print(f"qSupported negotiation failed ({e}), using default chunk size 0x{default:x}", file=sys.stderr)
    return default

  text = payload.decode(errors="replace")
  packet_size_hex = None
  for field in text.split(";"):
    if field.startswith("PacketSize="):
      packet_size_hex = field.split("=", 1)[1]
      break


  if packet_size_hex is None:
    print(f"qSupported reply had no PacketSize field ({text!r}), using default chunk size 0x{default:x}", file=sys.stderr)
    return default

  try:
    reported_size = int(packet_size_hex, 16)

  except ValueError:
    print(f"Couldn't parse PacketSize={packet_size_hex!r}, using default chunk size 0x{default:x}", file=sys.stderr)
    return default

  # reported_size is the max total packet size (hex-encoded payload +
  # framing). Our 'm addr,length' read requests hex-encode the
  # returned data 2 bytes per raw byte, so raw bytes we can safely
  # request is roughly reported_size/2, minus a safety margin for
  # packet framing ('$', '#xx', command prefix chars).
  safe_chunk = (reported_size // 2) - safety_margin
  if safe_chunk < 256:
    print(f"Negotiated PacketSize=0x{reported_size:x} yields a tiny safe chunk (0x{safe_chunk:x}) - falling back to default 0x{default:x}", file=sys.stderr)
    return default

  print(f"Negotiated gdbstub PacketSize=0x{reported_size:x} -> using chunk size 0x{safe_chunk:x}", file=sys.stderr)
  return safe_chunk


def read_memory(sock, addr, length):
  send_packet(sock, f"m{addr:x},{length:x}".encode())
  payload = recv_ack_or_packet(sock)
  if payload.startswith(b"E"):
    raise RuntimeError(f"Read failed: {payload}")

  return bytes.fromhex(payload.decode())


def write_memory(sock, addr, data: bytes):
  hex_data = data.hex()
  send_packet(sock, f"M{addr:x},{len(data):x}:{hex_data}".encode())
  payload = recv_ack_or_packet(sock)
  if payload != b"OK":
    raise RuntimeError(f"Write failed: {payload}")


def write32(sock, addr, value: int):
  """Write a 32-bit little-endian integer."""
  data = value.to_bytes(4, byteorder="little", signed=False)
  write_memory(sock, addr, data)


def read32(sock, addr) -> int:
  """Read a 32-bit little-endian integer."""
  data = read_memory(sock, addr, 4)
  return int.from_bytes(data, byteorder="little", signed=False)


def cmd_read_code(sock, addr, length=32):
  data = read_memory(sock, addr, length)
  print(f"Code at 0x{addr:08x}:")
  print(data.hex())


def cmd_continue(sock):
  send_packet(sock, b"c")

  # Don't wait for an ack/reply - in no-ack mode there may be nothing
  # sent back at all until the target stops again (breakpoint, etc),
  # and we don't want to block indefinitely here.
  # print("Sent continue - guest should be running again")


def cmd_detach(sock):
  send_packet(sock, b"D")
  print("Detached - guest should be running again")


def set_watchpoint(sock, addr, length, kind=b"2"):
  """Set a hardware watchpoint on [addr, addr+length).
  kind: b'2' = write watchpoint, b'3' = read watchpoint,
        b'4' = access (read or write) watchpoint."""
  send_packet(sock, f"Z{kind.decode()},{addr:x},{length:x}".encode())
  payload = recv_ack_or_packet(sock)
  if payload != b"OK":
    raise RuntimeError(f"Failed to set watchpoint: {payload}")


def remove_watchpoint(sock, addr, length, kind=b"2"):
  send_packet(sock, f"z{kind.decode()},{addr:x},{length:x}".encode())
  payload = recv_ack_or_packet(sock)
  if payload != b"OK":
    raise RuntimeError(f"Failed to remove watchpoint: {payload}")


def wait_for_stop(sock):
  """Block until the target stops (e.g. watchpoint hit) and return the
  raw stop-reply packet payload (starts with 'T' or 'S')."""
  # No 'c' ack expected in no-ack mode; just block on the socket until
  # a full packet arrives. Reuse recv_packet's framing logic directly.
  buf = b""
  while b"#" not in buf or len(buf) < buf.index(b"#") + 3:
    chunk = sock.recv(4096)
    if not chunk:
      raise RuntimeError("Connection closed while waiting for stop")

    buf += chunk
  start = buf.index(b"$")
  end = buf.index(b"#", start)
  payload = buf[start + 1 : end]
  sock.sendall(b"+")
  return payload


IGNORE_RANGES = [(0xD5000, 0xDA000), (0xDD000, 0xDE000), (0x141000, 0x142000), (0x23000, 0x24000), (0x000DA1F0, 0x000DA1F2)]


def is_ignored(eip):
  return any(lo <= eip < hi for lo, hi in IGNORE_RANGES)


def read_all_registers(sock):
  """Send 'g' to read the full general-register set. Returns the raw
  hex string - caller decodes based on target register order."""
  send_packet(sock, b"g")
  payload = recv_ack_or_packet(sock)
  if payload.startswith(b"E"):
    raise RuntimeError(f"Register read failed: {payload}")

  return payload.decode()


# Standard i386 gdbstub register order (32-bit regs, little-endian hex
# in the 'g' response): eax ecx edx ebx esp ebp esi edi eip eflags cs
# ss ds es fs gs. Each register is 8 hex chars (4 bytes).
I386_REG_NAMES = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi", "eip", "eflags", "cs", "ss", "ds", "es", "fs", "gs"]


def try_read(sock, addr, length):
  # Registers are often not valid pointers; a failed read is expected here.
  try:
    return read_memory(sock, addr, length)

  except RuntimeError:
    return None


def parse_registers(hex_blob):
  regs = {}
  for i, name in enumerate(I386_REG_NAMES):
    chunk = hex_blob[i * 8 : (i + 1) * 8]
    if len(chunk) < 8:
      break

    # Register bytes are little-endian within their own hex encoding
    raw = bytes.fromhex(chunk)
    value = int.from_bytes(raw, byteorder="little")
    regs[name] = value

  return regs


TARGET_EIP = 0x000A7F63


def set_breakpoint(sock, addr):
  send_packet(sock, f"Z0,{addr:x},1".encode())
  reply = recv_packet(sock)
  print("breakpoint:", reply)


def remove_breakpoint(sock, addr):
  send_packet(sock, f"z0,{addr:x},1".encode())
  reply = recv_packet(sock)
  print("breakpoint removed:", reply)


def cmd_watch(watch_addr, length, hits, kind=b"2"):
  sock = connect()
  kind_name = {b"2": "write", b"3": "read", b"4": "access (r/w)"}[kind]
  print(f"Setting {kind_name} watchpoint on 0x{watch_addr:08x}, length {length}...")
  set_watchpoint(sock, watch_addr, length, kind=kind)

  seen = {} # eip -> hit count
  running = False
  try:
    i = 0
    while i < hits:
      send_packet(sock, b"c")
      running = True
      stop = wait_for_stop(sock).decode()
      running = False
      if f"watch:{watch_addr:x};" not in stop:
        raise RuntimeError(f"Stopped for a different reason than our watchpoint: {stop}")

      regs = parse_registers(read_all_registers(sock))
      eip = regs["eip"]
      if is_ignored(eip):
        continue

      i += 1
      seen[eip] = seen.get(eip, 0) + 1
      if seen[eip] > 1:
        continue

      # NOTE: for read/write watchpoints EIP is the instruction AFTER the access.
      print(f"\n=== NEW EIP 0x{eip:08x} (hit {i + 1}) ===")
      print("  regs: " + " ".join(f"{n}={regs[n]:08x}" for n in I386_REG_NAMES[:8]))
      code = read_memory(sock, eip - 32, 64)
      print(f"  code @ EIP-32: {code.hex()}")
      for name in ["eax", "ecx", "edx", "ebx", "esi", "edi", "ebp"]:
        data = try_read(sock, regs[name], 32)
        if data is not None:
          print(f"  [{name}=0x{regs[name]:08x}]: {data.hex()}")




  except KeyboardInterrupt:
    print("\nInterrupted.")
    if running:
      sock.sendall(b"\x03") # break the running guest
      wait_for_stop(sock)


  finally:
    remove_watchpoint(sock, watch_addr, length, kind=kind)
    cmd_continue(sock)
    print("Watchpoint removed, guest resumed.")
    print("\nDistinct EIPs:")
    for eip, n in sorted(seen.items(), key=lambda kv: -kv[1]):
      print(f"  0x{eip:08x}: {n} hits")



def cmd_dump(sock, addr, length, path, chunk_size=0x1000):
  with open(path, "wb") as f:
    pos = 0
    while pos < length:
      n = min(chunk_size, length - pos)

      try:
        data = read_memory(sock, addr + pos, n)

      except RuntimeError:
        data = b"\x00" * n

      f.write(data)
      pos += n


  print(f"Dumped {length:#x} bytes from {addr:#010x} to {path}")


def verify_translation(physical_addr, expected_byte, base_offset):
  """Read the byte at (physical_addr + base_offset) as a VIRTUAL
  address and check it matches what pmemsave saw at physical_addr.
  If it matches, base_offset is very likely the correct translation
  for this memory region."""
  sock = connect()
  virt_addr = physical_addr + base_offset
  data = read_memory(sock, virt_addr, 1)
  actual = data[0]
  print(f"Physical 0x{physical_addr:08x} + base 0x{base_offset:08x} = virtual 0x{virt_addr:08x}")
  print(f"Expected byte: 0x{expected_byte:02x}, got: 0x{actual:02x}")
  if actual == expected_byte:
    print("MATCH - this base_offset looks correct.")
  else:
    print("MISMATCH - try a different base_offset.")


def scan_for_all(sock, signature: bytes, start, end, chunk_size=0x1000):
  addr = start
  overlap_len = len(signature) - 1
  prev_tail = b""
  found = []

  while addr < end:
    try:
      chunk = read_memory(sock, addr, chunk_size)

    except RuntimeError:
      addr += chunk_size
      prev_tail = b""
      continue

    haystack = prev_tail + chunk
    idx = haystack.find(signature)
    while idx != -1:
      found.append(addr - len(prev_tail) + idx)
      idx = haystack.find(signature, idx + 1)

    prev_tail = chunk[-overlap_len:] if overlap_len else b""
    addr += chunk_size

  return found


def cmd_find(hex_bytes, start, end):
  signature = bytes.fromhex(hex_bytes)
  sock = connect()
  chunk_size = query_max_packet_size(sock)
  for a in scan_for_all(sock, signature, start, end, chunk_size=chunk_size):
    print(f"0x{a:08x}")

  cmd_continue(sock)


def scan_for_signature(sock, signature: bytes, start, end, chunk_size=0x1000):
  """Scan virtual address range [start, end) for `signature`, reading

  in optimized chunks.
  """
  addr = start
  sig_len = len(signature)
  overlap_len = sig_len - 1 if sig_len > 1 else 0
  prev_tail = b""
  faulted_chunks = 0
  total_chunks = 0

  while addr < end:
    total_chunks += 1
    if total_chunks & 2047 == 0:
      pct = 100 * (addr - start) / (end - start)
      print(
        f"  ...scanned to 0x{addr:08x} ({pct:.1f}%), {faulted_chunks}/{total_chunks} chunks faulted",
        file=sys.stderr,
      )

    try:
      chunk = read_memory(sock, addr, chunk_size)

    except RuntimeError:
      faulted_chunks += 1
      addr += chunk_size
      prev_tail = b""
      continue

    haystack = prev_tail + chunk
    idx = haystack.find(signature)
    if idx != -1:
      found_addr = addr - len(prev_tail) + idx
      print(
        f"Scan summary: {faulted_chunks}/{total_chunks} chunks faulted (unmapped)",
        file=sys.stderr,
      )
      return found_addr

    prev_tail = chunk[-overlap_len:] if overlap_len else b""
    addr += chunk_size

  print(
    f"Scan summary: {faulted_chunks}/{total_chunks} chunks faulted (unmapped) out of range 0x{start:08x}-0x{end:08x}",
    file=sys.stderr,
  )
  return None


def cmd_scan(snapshot_path, physical_addr, sig_len, start, end):
  with open(snapshot_path, "rb") as f:
    f.seek(physical_addr)
    signature = f.read(sig_len)

  print(f"Signature ({sig_len} bytes) at physical 0x{physical_addr:08x}: {signature.hex()}")

  sock = connect()
  chunk_size = query_max_packet_size(sock)
  found = scan_for_signature(sock, signature, start, end, chunk_size=chunk_size)
  if found is None:
    print("Signature not found in scanned range.")
  else:
    offset = found - physical_addr
    print(f"Found at virtual 0x{found:08x}")
    print(f"Translation offset (virtual - physical) = 0x{offset:08x}")


import struct


def writef(sock, addr, value: float):
  """Write a 32-bit float to guest memory."""
  data = struct.pack("<f", value)
  write_memory(sock, addr, data)


def readf(sock, addr) -> float:
  """Read a 32-bit float from guest memory."""
  data = read_memory(sock, addr, 4)
  return struct.unpack("<f", data)[0]


if __name__ == "__main__":
  if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

  mode = sys.argv[1]

  if mode == "read":
    sock = connect()
    addr = int(sys.argv[2], 16)
    length = int(sys.argv[3])
    data = read_memory(sock, addr, length)
    cmd_continue(sock)
    print(data.hex())
  elif mode == "dump":
    sock = connect()
    addr = int(sys.argv[2], 16)
    length = int(sys.argv[3], 0)
    path = sys.argv[4]
    cmd_dump(sock, addr, length, path)
    cmd_continue(sock)

  elif mode == "write":
    sock = connect()
    addr = int(sys.argv[2], 16)
    data = bytes.fromhex(sys.argv[3])
    write_memory(sock, addr, data)
    cmd_continue(sock)
    print("Write OK")
  elif mode == "verify":
    physical_addr = int(sys.argv[2], 16)
    expected_byte = int(sys.argv[3], 16)
    base_offset = int(sys.argv[4], 16)
    verify_translation(physical_addr, expected_byte, base_offset)
  elif mode == "continue":
    sock = connect()
    cmd_continue(sock)
  elif mode == "detach":
    sock = connect()
    cmd_detach(sock)
  elif mode == "write32":
    sock = connect()
    addr = int(sys.argv[2], 16)
    value = int(sys.argv[3])
    write32(sock, addr, value)
    cmd_continue(sock)
    print(f"Wrote {value} (0x{value:08x}) to 0x{addr:08x}")
  elif mode == "code":
    sock = connect()
    addr = int(sys.argv[2], 16)
    length = int(sys.argv[3], 0) if len(sys.argv) > 3 else 32
    cmd_read_code(sock, addr, length)
    cmd_continue(sock)
  elif mode == "read32":
    sock = connect()
    addr = int(sys.argv[2], 16)
    value = read32(sock, addr)
    cmd_continue(sock)
    print(f"{value} (0x{value:08x})")
  elif mode == "scan":
    snapshot_path = sys.argv[2]
    physical_addr = int(sys.argv[3], 16)
    sig_len = int(sys.argv[4])
    start = int(sys.argv[5], 16)
    end = int(sys.argv[6], 16)
    cmd_scan(snapshot_path, physical_addr, sig_len, start, end)
  elif mode == "find":
    cmd_find(sys.argv[2], int(sys.argv[3], 16), int(sys.argv[4], 16))
  elif mode == "watch":
    addr = int(sys.argv[2], 16)
    length = int(sys.argv[3])
    hits = int(sys.argv[4])
    kind = sys.argv[5].encode()
    cmd_watch(addr, length, hits, kind=kind)
  else:
    print(f"Unknown mode: {mode}")
    sys.exit(1)

