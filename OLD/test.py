import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, set_watchpoint, remove_watchpoint, send_packet, wait_for_stop, read_all_registers, parse_registers, read_memory, cmd_continue

ADDR = 0x4EAB80
s = connect()
set_watchpoint(s, ADDR, 4, kind=b"2")
try:
  for i in range(6):
    send_packet(s, b"c")
    wait_for_stop(s)
    regs = parse_registers(read_all_registers(s))
    ret = int.from_bytes(read_memory(s, regs["esp"], 4), "little")
    op = read_memory(s, ret - 5, 1)[0]
    print(f"{i}: eip=0x{regs['eip']:08x} ret=0x{ret:08x} byte@ret-5=0x{op:02x} (0xe8 = call)")
    if i == 0:
      print("code around ret:", read_memory(s, ret - 0x60, 0xA0).hex())



finally:
  remove_watchpoint(s, ADDR, 4, kind=b"2")
  cmd_continue(s)
  s.close()
