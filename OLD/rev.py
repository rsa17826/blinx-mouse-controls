import sys; sys.path.insert(0, ".")
from gdb_rsp import connect, write_memory, cmd_continue
sock = connect()
write_memory(sock, 0x232dd, bytes.fromhex("e8de7e0000"))
cmd_continue(sock)
