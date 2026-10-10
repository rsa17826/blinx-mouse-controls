# @category Analysis
# @ray: Dependency-based function ordering

import os
from ghidra.program.model.symbol import SourceType


def get_topological_order():
  fm = currentProgram.getFunctionManager()
  ref_manager = currentProgram.getReferenceManager()
  all_funcs = list(fm.getFunctions(True))

  # Map of function -> set of functions it calls
  call_graph = {}

  print("Analyzing call graph... (this may take a moment)")
  for func in all_funcs:
    calls = set()

    # FIXED: Added 'True' argument to getAddresses()
    # This tells Ghidra to return an iterator for the address set
    body_addresses = func.getBody().getAddresses(True)

    for addr in body_addresses:
      # Get references starting at this specific address
      refs = ref_manager.getReferencesFrom(addr)
      for ref in refs:
        # Only count references that point to the start of another function
        called_func = fm.getFunctionAt(ref.getToAddress())
        if called_func and called_func != func:
          calls.add(called_func.getEntryPoint())



    call_graph[func.getEntryPoint()] = calls

  ordered_addresses = []
  processed = set()
  remaining = set(call_graph.keys())

  # Iteratively find functions whose dependencies are already processed
  while remaining:
    progress = False
    for addr in list(remaining):
      dependencies = call_graph[addr]
      # If all functions called by this function are already in the 'processed' list
      if dependencies.issubset(processed):
        ordered_addresses.append(addr)
        processed.add(addr)
        remaining.remove(addr)
        progress = True


    # Handle cycles (recursion): if no progress is made, force-process one remaining func
    if not progress and remaining:
      # Pick a function with the fewest remaining dependencies to break the cycle
      best_candidate = min(remaining, key=lambda a: len(call_graph[a] - processed))
      ordered_addresses.append(best_candidate)
      processed.add(best_candidate)
      remaining.remove(best_candidate)


  # Save to file
  output_path = os.path.join(os.path.expanduser("~"), "ghidra_order.txt")
  with open(output_path, "w") as f:
    for addr in ordered_addresses:
      func = fm.getFunctionAt(addr)
      if func:
        f.write("{} {}\n".format(addr, func.getName()))



  print("Saved dependency-ordered list to: {}".format(output_path))


get_topological_order()
