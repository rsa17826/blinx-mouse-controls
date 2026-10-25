from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor


def main():
  OUTPUT_PATH = "/tmp/xref_scan_results.txt"

  decomp = DecompInterface()
  decomp.openProgram(currentProgram)
  monitor = ConsoleTaskMonitor()

  fm = currentProgram.getFunctionManager()
  funcs = fm.getFunctions(True)

  print("Scanning entire binary for '+ 0xb8)' and '+ 0xc0)' patterns...")

  count = 0
  match_count = 0

  with open(OUTPUT_PATH, "w") as out:
    out.write("Full-binary scan for '+ 0xb8)' / '+ 0xc0)' patterns\n")
    out.write("=" * 70 + "\n\n")

    for func in funcs:
      count += 1
      if count % 200 == 0:
        print("...scanned {} functions".format(count))

      results = decomp.decompileFunction(func, 30, monitor)
      if not results or not results.decompileCompleted():
        continue

      decomp_func = results.getDecompiledFunction()
      if not decomp_func:
        continue

      code = decomp_func.getC()
      has_b8 = "+ 0xb8)" in code
      has_c0 = "+ 0xc0)" in code

      if not (has_b8 or has_c0):
        continue

      if has_b8 and has_c0:
        status = "BOTH"
      elif has_b8:
        status = "b8"
      else:
        status = "c0"

      match_count += 1

      out.write("STATUS: {}\n".format(status))
      out.write("FUNCTION: {} @ {}\n".format(func.getName(), func.getEntryPoint()))
      out.write("-" * 70 + "\n")
      out.write(code)
      out.write("\n" + "=" * 70 + "\n\n")


  print("Scan complete. Total functions scanned: {}".format(count))
  print("Total matches written: {}".format(match_count))
  print("Results file: {}".format(OUTPUT_PATH))


# Execute within function scope
main()
