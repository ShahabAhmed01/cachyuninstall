"""Running-process correlation (§76).

Matches processes by executable basename against a package's known
executables. Uses /proc directly: read-only, no kill signals anywhere in
this module — CachyUninstall asks the user to close apps; it never force-kills
by default (§166).
"""

from __future__ import annotations

import os
from pathlib import Path

from cachyuninstall.core.identity import Identity


def running_pids_for(identity: Identity, proc: Path = Path("/proc")) -> list[int]:
    """PIDs whose executable basename matches one of the identity's binaries."""
    if not identity.executables:
        return []
    wanted = {e.lower() for e in identity.executables}
    out: list[int] = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        exe = entry / "exe"
        try:
            target = os.readlink(exe)
        except OSError:
            continue  # kernel thread / permission / raced exit — all fine
        name = target.rsplit("/", 1)[-1].split(" ")[0].lower()
        if name in wanted:
            out.append(int(entry.name))
    return out
