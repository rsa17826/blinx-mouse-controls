import time
from gdb_rsp import connect, read_all_registers, parse_registers, cmd_continue

for i in range(15):
  s = connect()
  raw = read_all_registers(s)
  cmd_continue(s)
  s.close()
  print(f"raw={raw[:72]}")
  regs = parse_registers(raw)
  print(f"{i}: eip=0x{regs['eip']:08x} esp=0x{regs['esp']:08x} eflags=0x{regs['eflags']:08x}")
  time.sleep(0.5)
