# @category Analysis
# @menupath Analysis.AI Renamer

import os
import json
import urllib.request
import urllib.error

from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.pcode import HighFunctionDBUtil

SERVER_URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL_NAME = "Meta-Llama-3.1-8B-Instruct"
ORDER_FILE = os.path.join(os.path.expanduser("~"), "ghidra_order.txt")
EXIT_FILE = os.path.join(os.path.expanduser("~"), "exit")
MAX_TOKENS = 1024 # a rename map should never need more; stops runaway generation
REQUEST_TIMEOUT = 300 # seconds; backstop so the script never blocks forever
MAX_CODE_CHARS = 12000 # skip huge decompiled functions


def ask_ai(code):
  prompt = f'You are an expert reverse engineer. Analyze the following decompiled C code. Suggest a meaningful name for the function and all its local variables. Return ONLY a JSON object with this structure: {{"function_name": "new_name", "variables": {{"old_var_name": "new_var_name"}}}} No explanations. \n\nCode:\n{code}'

  payload = {
    "messages": [
      {"role": "system", "content": "You output only valid JSON."},
      {"role": "user", "content": prompt},
    ],
    "response_format": {"type": "json_object"},
    "temperature": 0.2,
    "max_tokens": MAX_TOKENS,
    "repeat_penalty": 1.1, # llama-server extension; discourages loops
    "stream": False,
  }

  data = json.dumps(payload).encode("utf-8")

  try:
    req = urllib.request.Request(SERVER_URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
      res_body = response.read().decode("utf-8")

    outer_json = json.loads(res_body)
    choice = outer_json["choices"][0]
    if choice["finish_reason"] == "length":
      raise ValueError(f"output hit max_tokens ({MAX_TOKENS}), likely a runaway generation")

    return json.loads(choice["message"]["content"])

  except urllib.error.HTTPError as e:
    error_body = e.read().decode("utf-8") if e.fp else ""
    print(f"AI HTTP Error {e.code}: {e.reason} | Details: {error_body}")
    return None

  except Exception as e:
    print(f"AI Error: {e}")
    return None


def rename_logic():
  if not os.path.exists(ORDER_FILE):
    print("Order file not found. Run Script 1 first.")
    return

  try:
    prog = currentProgram

  except NameError:
    prog = getState().getCurrentProgram()

  decomp = DecompInterface()
  decomp.openProgram(prog)

  with open(ORDER_FILE, "r") as f:
    lines = f.readlines()

  for line in lines:
    if os.path.exists(EXIT_FILE):
      print("Exit file detected. Stopping script.")
      try:
        os.remove(EXIT_FILE)

      except Exception:
        pass

      break

    parts = line.split(maxsplit=1)
    if len(parts) < 2:
      continue

    addr_str, name = parts
    addr = prog.getAddressFactory().getAddress(addr_str.strip())
    func = prog.getFunctionManager().getFunctionAt(addr)

    if not func:
      continue

    if not func.getName().lower().startswith("fun_"):
      print(f"Skipping already renamed function: {func.getName()}")
      continue

    res = decomp.decompileFunction(func, 0, ConsoleTaskMonitor())
    if not res.decompileCompleted():
      continue

    decomp_func = res.getDecompiledFunction()
    if not decomp_func:
      continue

    code = decomp_func.getC()

    if len(code) > MAX_CODE_CHARS:
      print(f"Skipping {func.getName()}: decompiled code too large ({len(code)} chars)")
      continue

    print(f"Processing: {func.getName()}")
    suggestions = ask_ai(code)

    if not suggestions:
      continue

    # 1. Rename Function
    new_func_name = suggestions.get("function_name")
    if new_func_name:
      try:
        func.setName(new_func_name, SourceType.USER_DEFINED)

      except Exception as e:
        print(f"Failed to rename function {func.getName()}: {e}")


    # 2. Rename Local Variables & Parameters
    vars_map = suggestions.get("variables", {})
    if vars_map:
      high_func = res.getHighFunction()
      if high_func and high_func.getLocalSymbolMap():
        sym_iter = high_func.getLocalSymbolMap().getSymbols()
        while sym_iter.hasNext():
          high_symbol = sym_iter.next()
          old_name = high_symbol.getName()

          if old_name in vars_map:
            new_var_name = vars_map[old_name]
            try:
              # Correct method to rename HighSymbol in Ghidra
              HighFunctionDBUtil.updateDBVariable(high_symbol, new_var_name, None, SourceType.USER_DEFINED)

            except Exception as e:
              # Fallback: try setting via underlying symbol
              db_sym = high_symbol.getSymbol()
              if db_sym:
                try:
                  db_sym.setName(new_var_name, SourceType.USER_DEFINED)

                except Exception as inner_e:
                  print(f"Failed to rename symbol {old_name}: {inner_e}")

              else:
                print(f"Failed to rename high symbol {old_name}: {e}")







  print("Process completed.")


rename_logic()
