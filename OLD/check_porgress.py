# @category Analysis
# @menupath Analysis.AI Progress Checker

import os

ORDER_FILE = os.path.join(os.path.expanduser("~"), "ghidra_order.txt")


def check_progress():
  if not os.path.exists(ORDER_FILE):
    print("Order file not found at: {}".format(ORDER_FILE))
    return

  try:
    prog = currentProgram

  except NameError:
    prog = getState().getCurrentProgram()

  with open(ORDER_FILE, "r") as f:
    lines = f.readlines()

  total = 0
  done = 0
  not_done = 0

  for line in lines:
    line = line.strip()
    if not line:
      continue

    parts = line.split(maxsplit=1)
    addr_str = parts[0]

    addr = prog.getAddressFactory().getAddress(addr_str)
    func = prog.getFunctionManager().getFunctionAt(addr)

    if not func:
      continue

    total += 1
    current_name = func.getName()

    # If it still starts with FUN_, it hasn't been renamed by the AI yet
    if current_name.lower().startswith("fun_"):
      not_done += 1
    else:
      done += 1


  if total == 0:
    print("No valid functions found from ghidra_order.txt.")
    return

  percentage = (float(done) / float(total)) * 100.0
  print("Progress: {}/{} ({:.2f}%) | Renamed: {}, Remaining: {}".format(done, total, percentage, done, not_done))


check_progress()
