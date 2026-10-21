#!python
from gdb_rsp import cmd_continue, connect, write_memory

sock = connect()
# write_memory(sock, 0xF0A9474E, bytes.fromhex("77")) # spike bullet
# write_memory(sock, 0xF0A9474E, bytes.fromhex("4f")) # super bomb
#
val = 0x0
while 1:
  print(val, val.to_bytes(1, byteorder="big"))
  write_memory(sock, 0xF0A9474E, val.to_bytes(1, byteorder="big"))
  print(val)
  val += 0x1
  print(val)
  cmd_continue(sock=sock)
  _ = input(val)

# write_memory(sock, 0xF0A9474F, bytes.fromhex(val))
# write_memory(sock, 0xF0A94750, bytes.fromhex(val))
# write_memory(sock, 0xF0A94751, bytes.fromhex(val))
# write_memory(sock, 0xF0A94752, bytes.fromhex(val))
# write_memory(sock, 0xF0A94753, bytes.fromhex(val))
# write_memory(sock, 0xF0A94754, bytes.fromhex(val))
# write_memory(sock, 0xF0A94755, bytes.fromhex(val))
# write_memory(sock, 0xF0A94756, bytes.fromhex(val))
# write_memory(sock, 0xF0A94757, bytes.fromhex(val))
