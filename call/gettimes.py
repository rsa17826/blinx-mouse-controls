#!/usr/bin/env python
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
import gdb_rsp

sock = gdb_rsp.connect()
addrs = (0xF0A95758, 0xF0A95784, 0xF0A957B0, 0xF0A957DC, 0xF0A95808, 0xF0A95834, 0xF0A95860, 0xF0A9588C, 0xF0A958B8, 0xF0A958E4, 0xF0A95910, 0xF0A9593C, 0xF0A95A18, 0xF0A95A44, 0xF0A95A70, 0xF0A95A9C, 0xF0A95968, 0xF0A95994, 0xF0A959C0, 0xF0A959EC, 0xF0A95AC8, 0xF0A95AF4, 0xF0A95B20, 0xF0A95B4C, 0xF0A95C28, 0xF0A95C54, 0xF0A95C80, 0xF0A95CAC, 0xF0A95CD8, 0xF0A95D04, 0xF0A95D30, 0xF0A95D5C, 0xF0A95D88)
lv = 0
for addr in addrs:
  frames = gdb_rsp.read32(sock, addr)
  total_ms = int((frames / 30.0) * 1000)

  m = total_ms // 60000
  s = (total_ms % 60000) // 1000
  ms = total_ms % 1000
  print(f"{(lv // 4) + 1}-{(lv % 4) + 1}: {m:02d}:{s:02d}.{ms:03d}")
  lv += 1

gdb_rsp.cmd_continue(sock)
