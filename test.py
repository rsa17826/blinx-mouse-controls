import math, struct
from gdb_rsp import connect, read_memory, cmd_continue
s = connect()
d = read_memory(s, 0x4eaa20, 0x1c0)
cmd_continue(s)
f = lambda o: struct.unpack_from("<f", d, o)[0]
x, y, z = f(0x160), f(0x164), f(0x168)
print(f"dir=({x:.3f},{y:.3f},{z:.3f}) len={math.sqrt(x*x+y*y+z*z):.3f} "
      f"yaw={math.atan2(x, z):.3f} heading={f(0x8c):.3f} state={d[2]} sub={d[0x20]} surf={d[0x1d]}")