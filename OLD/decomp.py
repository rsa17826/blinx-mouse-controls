import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

sock = connect()
start = 0x2322F - 160
code = read_memory(sock, start, 176)
md = Cs(CS_ARCH_X86, CS_MODE_32)
for insn in md.disasm(code, start):
  marker = " <-- (known caller block starts here)" if insn.address == 0x2322F else ""
  print(f"0x{insn.address:08x}: {insn.mnemonic} {insn.op_str}{marker}")

256
