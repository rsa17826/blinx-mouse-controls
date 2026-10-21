from gdb_rsp import write_memory, connect, cmd_continue
sock = connect()
# Position hooks
write_memory(sock, 0x2312c, bytes.fromhex('d90524d79d00'))
write_memory(sock, 0x23141, bytes.fromhex('d90528d79d00'))
write_memory(sock, 0x23151, bytes.fromhex('d9052cd79d00'))
# Pitch / yaw hooks
write_memory(sock, 0x2316d, bytes.fromhex('d80d30a21800'))
write_memory(sock, 0x23183, bytes.fromhex('d80d30a21800'))
# Roll hook
write_memory(sock, 0x23199, bytes.fromhex('d80d30a21800'))
# Strafe hook (v1 site - no-op if never installed, harmless to write original bytes)
write_memory(sock, 0xdae77, bytes.fromhex('83c40c5f5e'))
# Strafe hook (v2 site - the working one)
write_memory(sock, 0xdae7a, bytes.fromhex('5f5e5d5b81c4b0020000'))
cmd_continue(sock)
