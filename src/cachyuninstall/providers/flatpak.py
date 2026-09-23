"""Flatpak provider (D7).

Flatpak is optional. When `flatpak` is absent the provider reports
unavailable and contributes zero rows — no errors, no installs.

Discovery + removal go through the provider's own CLI with structured argv
(never shell). Application data removal uses `--delete-data` (§69) instead of
manual ~/.var/app deletion.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from cachyuninstall.core.errors import ProviderUnavailable, TransactionFailed
from cachyuninstall.core.models import Origin, ProviderKind
from cachyuninstall.providers.base import Installation

_TIMEOUT = 30


@dataclass(slots=True)
class FlatpakApp:
    app_id: str
    name: str
    version: str
    scope: str  # "user" | "system"
    size_bytes: int


class FlatpakProvider:
    kind = ProviderKind.FLATPAK

    def __init__(self, binary: str = "flatpak") -> None:
        self._binary = binary

    def is_available(self) -> bool:
        return shutil.which(self._binary) is not None

    def _run(self, args: list[str]) -> str:
        try:
            proc = subprocess.run(
                [self._binary, *args],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise ProviderUnavailable("Flatpak is not installed.") from exc
        except subprocess.TimeoutExpired as exc:
            raise TransactionFailed("Flatpak did not answer in time.") from exc
        if proc.returncode != 0:
            raise TransactionFailed("Flatpak operation failed.", detail=proc.stderr.strip()[:500])
        return proc.stdout

    def list_installations(self) -> list[Installation]:
        if not self.is_available():
            return []
        raw = self._run(["list", "--app", "--columns=application,name,version,installation,origin"])
        out: list[Installation] = []
        for line in raw.splitlines():
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            app_id, name = cols[0], cols[1]
            version = cols[2] if len(cols) > 2 else ""
            scope = cols[3] if len(cols) > 3 else "user"
            out.append(
                Installation(
                    instance_id=f"flatpak:{scope}:{app_id}",
                    provider=ProviderKind.FLATPAK,
                    name=app_id,
                    display_name=name or app_id,
                    version=version,
                    origin=Origin.FLATPAK,
                    size_bytes=0,  # measured lazily; 0 avoids ghastly du calls at list time
                )
            )
        return out

    # ------------------------------------------------------------- removal
    def build_uninstall_argv(self, app_id: str, scope: str) -> list[str]:
        # The same app id can live in BOTH scopes. Without an explicit scope
        # flag flatpak does not fail — it prompts interactively
        # ("Similar installed refs found … Which do you want to use (0 to
        # abort)?"), which hangs until timeout in the GUI's captured
        # subprocess (physical probe, D24). Always pin the scope.
        flag = "--system" if scope == "system" else "--user"
        return [self._binary, "uninstall", flag, "--delete-data", "-y", app_id]

    def uninstall(self, app_id: str, scope: str) -> None:
        argv = self.build_uninstall_argv(app_id, scope)
        self._run(argv[1:])  # _run prepends self._binary

    # ------------------------------------------------------------ info json
    def info_json(self, app_id: str, scope: str) -> dict[str, object]:
        # Pin the scope here too (D24): with the app in both installations
        # an unflagged `flatpak info` returns an arbitrary match instead of
        # the requested scope's (physical probe: --system/--user both valid).
        flag = "--system" if scope == "system" else "--user"
        args = ["info", flag, "--show-size"]
        raw = self._run([*args, app_id])
        out: dict[str, object] = {}
        for line in raw.splitlines():
            key, _, value = line.partition(":")
            if value.strip():
                out[key.strip()] = value.strip()
        return out


def parse_size_bytes(text: str) -> int:
    """'1,2 MB' / '812,3 kB' → bytes (locale '.' thousands, ',' decimals)."""
    cleaned = text.replace("\xa0", " ").strip()
    for unit, mult in (
        ("GB", 1000**3),
        ("MB", 1000**2),
        ("kB", 1000),
        ("bytes", 1),
        ("B", 1),
        ("GiB", 1024**3),
        ("MiB", 1024**2),
        ("KiB", 1024),
    ):
        if cleaned.endswith(unit):
            num = cleaned[: -len(unit)].strip().replace(".", "").replace(",", ".")
            try:
                return int(float(num) * mult)
            except ValueError:
                return -1
    return -1
