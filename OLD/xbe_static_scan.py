#!/usr/bin/env python3
"""Static analysis of a raw .xbe file: parse just enough of the XBE
header to map file offsets <-> virtual addresses, search for the
fixed-point angle-conversion constant (65536/(2*pi)) in the data
sections, then disassemble the executable section(s) and grep for any
instruction whose operand text references that constant's address.

This avoids all the live-emulator freeze/race/noise issues we hit
scanning xemu's runtime memory - the XBE on disk is static, so a
match here is unambiguous and doesn't need translation-offset guessing.

XBE header layout used here (offsets from the public XBE format docs,
e.g. Cxbx-Reloaded/openxdk):
    0x00        magic (b'XBEH')
    0x104       BaseAddress (u32)
    0x11C       NumberOfSections (u32)
    0x120       SectionHeadersAddress (u32, VIRTUAL address)
Each section header is 56 bytes:
    0x00 Flags (u32) - bit 0x4 commonly marks the section executable
    0x04 VirtualAddress (u32)
    0x08 VirtualSize (u32)
    0x0C RawAddress (u32) - FILE OFFSET
    0x10 RawSize (u32)
    (remaining fields unused here)

Usage:
    python3 xbe_static_scan.py /path/to/default.xbe
"""
import struct
import sys

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:
    print("capstone not available in this environment. Run via:")
    print('  nix-shell -p python3Packages.capstone --run "python3 xbe_static_scan.py <xbe path>"')
    sys.exit(1)


def parse_xbe(path):
    with open(path, "rb") as f:
        data = f.read()

    if data[:4] != b"XBEH":
        raise ValueError(f"Not an XBE file (magic was {data[:4]!r})")

    base_address = struct.unpack_from("<I", data, 0x104)[0]
    num_sections = struct.unpack_from("<I", data, 0x11C)[0]
    section_headers_va = struct.unpack_from("<I", data, 0x120)[0]

    # The header region itself is identity-mapped: virtual base_address
    # corresponds to file offset 0, so any virtual address inside the
    # header region converts to a file offset by simple subtraction.
    section_table_file_offset = section_headers_va - base_address

    sections = []
    for i in range(num_sections):
        off = section_table_file_offset + i * 56
        flags = struct.unpack_from("<I", data, off + 0x00)[0]
        vaddr = struct.unpack_from("<I", data, off + 0x04)[0]
        vsize = struct.unpack_from("<I", data, off + 0x08)[0]
        raddr = struct.unpack_from("<I", data, off + 0x0C)[0]
        rsize = struct.unpack_from("<I", data, off + 0x10)[0]
        executable = bool(flags & 0x4)
        sections.append({
            "flags": flags, "vaddr": vaddr, "vsize": vsize,
            "raddr": raddr, "rsize": rsize, "executable": executable,
        })

    return data, base_address, sections


def file_offset_to_va(sections, file_offset):
    for s in sections:
        if s["raddr"] <= file_offset < s["raddr"] + s["rsize"]:
            return s["vaddr"] + (file_offset - s["raddr"])
    return None


def va_to_file_offset(sections, va):
    for s in sections:
        if s["vaddr"] <= va < s["vaddr"] + s["vsize"]:
            file_off = s["raddr"] + (va - s["vaddr"])
            if file_off < s["raddr"] + s["rsize"]:
                return file_off
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    xbe_path = sys.argv[1]
    data, base_address, sections = parse_xbe(xbe_path)

    print(f"Base address: 0x{base_address:08x}")
    print(f"{len(sections)} section(s):")
    for s in sections:
        exe_tag = " [EXECUTABLE]" if s["executable"] else ""
        print(f"  VA=0x{s['vaddr']:08x} size=0x{s['vsize']:08x}  "
              f"file_off=0x{s['raddr']:08x} size=0x{s['rsize']:08x}{exe_tag}")

    # --- Search for the constant ---
    target_exact = struct.pack("<f", 10430.765625)  # confirmed live-memory value
    target_precise = struct.pack("<f", 65536.0 / (2 * 3.14159265358979))

    candidates = set()
    for label, sig in [("exact 10430.765625", target_exact),
                        ("precise 65536/(2pi)", target_precise)]:
        idx = 0
        while True:
            idx = data.find(sig, idx)
            if idx == -1:
                break
            va = file_offset_to_va(sections, idx)
            print(f"Found '{label}' at file offset 0x{idx:08x} "
                  f"-> VA 0x{va:08x}" if va else
                  f"Found '{label}' at file offset 0x{idx:08x} (no VA mapping)")
            if va:
                candidates.add(va)
            idx += 1

    if not candidates:
        print("\nNo exact match found. The value may be rounded "
              "differently in this build - consider a numpy tolerance "
              "scan over the raw file bytes similar to the earlier "
              "live-memory version, reading `data` as float32 array.")
        return

    # --- Disassemble executable sections and grep for references ---
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    exec_sections = [s for s in sections if s["executable"]]
    print(f"\nDisassembling {len(exec_sections)} executable section(s) "
          f"and searching for references to: "
          f"{', '.join(hex(c) for c in candidates)}")

    hex_needles = [f"0x{c:x}" for c in candidates]

    for s in exec_sections:
        code = data[s["raddr"]: s["raddr"] + s["rsize"]]
        for insn in md.disasm(code, s["vaddr"]):
            op = insn.op_str
            if any(needle in op for needle in hex_needles):
                print(f"0x{insn.address:08x}: {insn.mnemonic} {insn.op_str}")


if __name__ == "__main__":
    main()
