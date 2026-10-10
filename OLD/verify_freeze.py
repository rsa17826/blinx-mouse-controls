#!/usr/bin/env python3
"""Verification-only patch: NOP out the six store instructions that
write camera position (0x9dd650/654/658) and the pitch/yaw/roll copy
(0x9dd7e0/e4/e8) every frame. This does NOT add any camera control -
it just freezes those six floats at whatever value they hold at the
moment of patching, so we can visually confirm the camera stops
following/rotating with the player. That confirms (or disproves)
these are the correct hook points before we build real mouse-look
logic on top.

Exact instruction lengths (confirmed via earlier disassembly):
    0x000232aa: mov dword ptr [0x9dd650], eax   (5 bytes - A3 form)
    0x000232b3: mov dword ptr [0x9dd654], ecx   (6 bytes)
    0x000232bd: mov dword ptr [0x9dd658], edx   (6 bytes)
    0x000232cc: mov dword ptr [0x9dd7e0], eax   (5 bytes - A3 form)
    0x000232d1: mov dword ptr [0x9dd7e4], ecx   (6 bytes)
    0x000232d7: mov dword ptr [0x9dd7e8], edx   (6 bytes)

Each is replaced with an equal-length run of 0x90 (NOP) so no other
instruction boundaries shift.

Usage:
    python3 verify_freeze.py patch     - install the NOP patch
    python3 verify_freeze.py revert    - restore original bytes
    python3 verify_freeze.py status    - show current bytes at each site
"""
import sys

sys.path.insert(0, ".")
from gdb_rsp import connect, read_memory, write_memory, cmd_continue  # noqa: E402

SITES = [
    (0x000232aa, 5, "mov [0x9dd650], eax"),
    (0x000232b3, 6, "mov [0x9dd654], ecx"),
    (0x000232bd, 6, "mov [0x9dd658], edx"),
    (0x000232cc, 5, "mov [0x9dd7e0], eax"),
    (0x000232d1, 6, "mov [0x9dd7e4], ecx"),
    (0x000232d7, 6, "mov [0x9dd7e8], edx"),
]

BACKUP_FILE = "verify_freeze_backup.txt"


def cmd_status():
    sock = connect()
    for addr, length, label in SITES:
        data = read_memory(sock, addr, length)
        print(f"0x{addr:08x} ({label}): {data.hex()}")
    cmd_continue(sock)


def cmd_patch():
    sock = connect()

    # Save originals first, before writing anything, so a partial
    # failure never leaves us without a way to revert.
    backups = []
    for addr, length, label in SITES:
        original = read_memory(sock, addr, length)
        backups.append((addr, original.hex()))
        print(f"Backed up 0x{addr:08x} ({label}): {original.hex()}")

    with open(BACKUP_FILE, "w") as f:
        for addr, hexbytes in backups:
            f.write(f"{addr:x} {hexbytes}\n")
    print(f"Backup written to {BACKUP_FILE}")

    for addr, length, label in SITES:
        write_memory(sock, addr, bytes([0x90] * length))
        print(f"Patched 0x{addr:08x} ({label}) -> {length} NOPs")

    cmd_continue(sock)
    print("\nPatch installed. Camera position/pitch/yaw/roll should now "
          "be FROZEN - move around and rotate the stick; the camera "
          "should NOT follow or rotate at all. If it still moves "
          "normally, these are not (solely) the right hook points.")


def cmd_revert():
    import os
    if not os.path.exists(BACKUP_FILE):
        print(f"No backup file ({BACKUP_FILE}) found - nothing to revert, "
              f"or patch was never installed via this script.")
        return

    sock = connect()
    with open(BACKUP_FILE) as f:
        for line in f:
            addr_hex, hexbytes = line.strip().split(" ", 1)
            addr = int(addr_hex, 16)
            data = bytes.fromhex(hexbytes)
            write_memory(sock, addr, data)
            print(f"Restored 0x{addr:08x}: {hexbytes}")
    cmd_continue(sock)
    print("\nReverted. Camera should follow/rotate normally again.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("patch", "revert", "status"):
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "patch":
        cmd_patch()
    elif mode == "revert":
        cmd_revert()
    elif mode == "status":
        cmd_status()
