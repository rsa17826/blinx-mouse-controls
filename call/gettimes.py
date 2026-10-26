#!/usr/bin/env python
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))
import gdb_rsp

sock = gdb_rsp.connect()
ranks = (
  (900, 1800, 2700, 3600),
  (1500, 2700, 4500, 6300),
  (1650, 2700, 3600, 6300),
  (900, 1500, 2700, 5400),
  (1950, 3000, 5400, 7200),
  (2400, 3300, 5400, 9000),
  (2700, 3600, 5400, 9900),
  (1500, 2400, 4500, 7200),
  (3000, 4500, 7200, 11700),
  (4800, 6600, 9000, 12600),
  (6450, 7200, 10800, 13500),
  (1050, 1800, 3600, 5400),
  (7500, 9300, 12600, 14400),
  (7500, 9900, 12600, 14400),
  (6750, 7800, 11700, 14400),
  (2400, 3600, 5400, 9000),
  (6900, 10800, 12600, 15300),
  (8700, 11700, 13500, 16200),
  (9450, 12600, 14400, 16200),
  (3000, 4050, 6300, 9900),
  (8100, 9300, 12600, 16200),
  (11400, 12600, 14400, 16200),
  (8100, 9600, 13500, 16200),
  (6000, 7200, 9000, 10800),
  (10200, 12600, 14400, 17100),
  (13200, 14400, 16200, 17100),
  (14400, 15300, 16200, 17100),
  (6300, 8100, 9900, 12600),
  (7800, 9900, 13500, 17100),
  (12150, 12600, 14400, 17100),
  (12600, 14400, 15300, 17100),
  (7200, 9000, 10800, 12600),
  (7200, 10800, 14400, 17100),
)
addrs = (0xF0A95758, 0xF0A95784, 0xF0A957B0, 0xF0A957DC, 0xF0A95808, 0xF0A95834, 0xF0A95860, 0xF0A9588C, 0xF0A958B8, 0xF0A958E4, 0xF0A95910, 0xF0A9593C, 0xF0A95A18, 0xF0A95A44, 0xF0A95A70, 0xF0A95A9C, 0xF0A95968, 0xF0A95994, 0xF0A959C0, 0xF0A959EC, 0xF0A95AC8, 0xF0A95AF4, 0xF0A95B20, 0xF0A95B4C, 0xF0A95C28, 0xF0A95C54, 0xF0A95C80, 0xF0A95CAC, 0xF0A95CD8, 0xF0A95D04, 0xF0A95D30, 0xF0A95D5C, 0xF0A95D88)
lv = -1
matches = "".join(sys.argv[1:])
for addr in addrs:
  lv += 1
  world = (lv // 4) + 1
  sublv = (lv % 4) + 1
  if len(sys.argv) < 2 or f"{world}{sublv}" in matches or f"{world}-{sublv}" in matches:
    frames = gdb_rsp.read32(sock, addr)
    total_ms = int((frames / 30.0) * 1000)

    m = total_ms // 60000
    s = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    levelRanks = ranks[lv]
    i = -1
    for i in range(0, 4 + 1, 1):
      if frames < levelRanks[i]:
        break


    print(f"{world}-{sublv}: {m:02d}:{s:02d}.{ms:03d} {'SABCD_'[i]}+ {total_ms}")


gdb_rsp.cmd_continue(sock)
