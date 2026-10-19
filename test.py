from gdb_rsp import connect, read_memory, cmd_continue
s = connect()
print(read_memory(s, 0x141fbd, 48).hex())
cmd_continue(s)