import sys; sys.path.insert(0, ".")
from gdb_rsp import connect, write_memory, cmd_continue
import struct

sock = connect()
write_memory(sock, 0x9dd7e4, struct.pack("<f", 3.14159)) # yaw = pi, should face opposite direction
cmd_continue(sock)
