#!/usr/bin/env python3
"""Python client for the IMan input-manager daemon (see inputevents.go),
ModeFilter only. Lets us subscribe to specific keyboard/mouse events,
receive them over a Unix socket, and explicitly block them from
reaching anything else (the real desktop/game window) - instead of
reading raw evdev events directly, which the OS ALSO still delivers to
whatever has input focus, causing double-input.

Wire protocol (from inputevents.go):

Handshake (client -> server), once per connection:
    1 byte  mode            (ModeFilter = 1)
    1 byte  name length N
    N bytes name
    4 bytes pid, little-endian

FilterSpec (client -> server), ModeFilter connections only, sent
immediately after the handshake:
    1 byte  flags (bit0 = keyboards, bit1 = mice)
    2 bytes keycode count, little-endian uint16
    count * 2 bytes keycodes, little-endian uint16 each

WireEvent (server -> client), repeated for each matching event:
    8 bytes  Sec    (int64, little-endian)
    8 bytes  Usec   (int64, little-endian)
    2 bytes  Type   (uint16)
    2 bytes  Code   (uint16)
    4 bytes  Value  (int32)
    8 bytes  Seq    (uint64)
    64 bytes DeviceID (NUL-padded)
    = 96 bytes total, no padding between fields (matches Go's
    encoding/binary behaviour for fixed-width primitive fields).

FilterResponse (client -> server), one per received WireEvent:
    8 bytes Seq   (uint64, little-endian)
    1 byte  Block (0 = let it through, 1 = block it)
    = 9 bytes total.

"""

import socket
import struct

SOCKET_PATH = "/tmp/kbd_manager.sock"

MODE_LISTEN = 0
MODE_FILTER = 1
MODE_INJECTION = 2
MODE_VIRT_LISTEN = 3

# Standard Linux input-event-codes.h types (matches evdev.ecodes).
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

_EVENT_STRUCT = struct.Struct("<qqHHiQ64s") # matches WireEvent exactly
_RESPONSE_STRUCT = struct.Struct("<QB") # matches FilterResponse exactly


def _recv_exact(sock, n):
  buf = b""
  while len(buf) < n:
    chunk = sock.recv(n - len(buf))
    if not chunk:
      raise ConnectionError("IMan connection closed while reading")

    buf += chunk

  return buf


class FilterConnection:
  def __init__(self, name, keyboards=False, mice=False, keycodes=None):
    """Connect in ModeFilter, subscribing only to what's needed.
    Prefer a narrow `keycodes` list over `keyboards=True` where
    possible - keyboards=True forwards EVERY keystroke on the
    system to this client for a block/pass decision, which is
    both slower and riskier (a bug here could stall typing
    elsewhere) than only asking for the specific keys you use."""
    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.sock.connect(SOCKET_PATH)

    name_bytes = name.encode()[:255]
    pid = __import__("os").getpid()
    handshake = bytes([MODE_FILTER, len(name_bytes)]) + name_bytes
    handshake += struct.pack("<I", pid & 0xFFFFFFFF)
    self.sock.sendall(handshake)

    keycodes = keycodes or []
    flags = (0x01 if keyboards else 0) | (0x02 if mice else 0)
    spec = bytes([flags]) + struct.pack("<H", len(keycodes))
    for code in keycodes:
      spec += struct.pack("<H", code)

    self.sock.sendall(spec)

  def read_event(self):
    """Block until the next matching event arrives. Returns a dict
    with keys: sec, usec, type, code, value, seq, device_id."""
    raw = _recv_exact(self.sock, _EVENT_STRUCT.size)
    sec, usec, type_, code, value, seq, device_id_raw = _EVENT_STRUCT.unpack(raw)
    nul = device_id_raw.find(b"\x00")
    device_id = device_id_raw[: nul if nul != -1 else None].decode(errors="replace")
    return {
      "sec": sec,
      "usec": usec,
      "type": type_,
      "code": code,
      "value": value,
      "seq": seq,
      "device_id": device_id,
    }

  def block_input(self, seq, block: bool):
    """Respond to the event identified by `seq` (from read_event).
    block=True prevents it from reaching anything else (the real
    desktop/game)"""
    payload = _RESPONSE_STRUCT.pack(seq, 1 if block else 0)
    self.sock.sendall(payload)

  def close(self):
    try:
      self.sock.sendall(b"\xff")

    except OSError:
      pass

    self.sock.close()

