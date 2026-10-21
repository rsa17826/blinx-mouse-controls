#!python
from gdb_rsp import cmd_continue, connect, write_memory

sock = connect()
# write_memory(sock, 0xF0A9474E, bytes.fromhex("77")) # spike bullet
# write_memory(sock, 0xF0A9474E, bytes.fromhex("4f")) # super bomb
#
import sys

val = int(sys.argv[1], 10)
write_memory(sock, 0xF0A9474E, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A9474F, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94750, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94751, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94752, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94753, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94754, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94755, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94756, val.to_bytes(1, byteorder="big"))
write_memory(sock, 0xF0A94757, val.to_bytes(1, byteorder="big"))
cmd_continue(sock=sock)
print(val + 0x1)

# write_memory(sock, 0xF0A9474F, bytes.fromhex(val))
# write_memory(sock, 0xF0A94750, bytes.fromhex(val))
# write_memory(sock, 0xF0A94751, bytes.fromhex(val))
# write_memory(sock, 0xF0A94752, bytes.fromhex(val))
# write_memory(sock, 0xF0A94753, bytes.fromhex(val))
# write_memory(sock, 0xF0A94754, bytes.fromhex(val))
# write_memory(sock, 0xF0A94755, bytes.fromhex(val))
# write_memory(sock, 0xF0A94756, bytes.fromhex(val))
# write_memory(sock, 0xF0A94757, bytes.fromhex(val))
