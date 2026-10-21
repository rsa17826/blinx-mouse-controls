#!python
from gdb_rsp import cmd_continue, connect, write_memory

sock = connect()

thing = 0x54.to_bytes(1, byteorder="big", signed=False)
write_memory(sock, 0xF0A9474D, 0xA.to_bytes(1, byteorder="big", signed=False))
for addr in range(0xF0A9474E, 0xF0A94757 + 0x1, 0x1):
  write_memory(sock, addr, thing)

cmd_continue(sock)
