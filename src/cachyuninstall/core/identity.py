"""Application identity engine.

Builds the graph  package ↔ desktop entry ↔ executable  that lets the UI show
human-readable applications instead of raw package names, and that feeds the
leftover scanner reliable identifier sets.

Security notes:
  * .desktop files are parsed as untrusted metadata. The Exec/Exec-line is
    stored as text for display but is NEVER executed anywhere (#177, D-spec).
  * Field codes (%f %F %u %U %i %c %k ...) are stripped only for *displayed
    binary-name discovery*; we do not reconstruct command lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cachyuninstall.core.models import PackageName, PackageRecord

_DESKTOP_GROUP = "Desktop Entry"
_KEY_SPLIT = re.compile(r"\s*;\s*")
_LOCALE_SUFFIX = re.compile(r"^(?P<key>[A-Za-z-]+)(?:\[[^\]]*\])?$")
_FIELD_CODE = re.compile(r"%[a-zA-Z%]")
_BIN_PREFIXES = ("usr/bin/", "usr/sbin/", "bin/", "sbin/")


@dataclass(frozen=True, slots=True)
class DesktopEntry:
    """Parsed [Desktop Entry] group of one .desktop file."""

    path: Path
    desktop_id: str  # filename without .desktop, e.g. "org.kde.dolphin"
    name: str  # localized value preferred by caller locale
    generic_name: str
    comment: str
    exec_line: str  # raw, untrusted — never executed
    icon: str
    categories: tuple[str, ...]
    keywords: tuple[str, ...]
    mime_types: tuple[str, ...]
    startup_wm_class: str
    no_display: bool
    hidden: bool
    terminal: bool

    @property
    def exec_binary_guess(self) -> str:
        """Best-effort basename of the invoked binary, or ''.

        Used ONLY as an identity hint; correctness does not depend on it.
        """
        if not self.exec_line:
            return ""
        # Strip field codes and split respecting simple quoting.
        cleaned = _FIELD_CODE.sub("", self.exec_line).strip()
        if not cleaned:
            return ""
        first = cleaned.split()[0].strip("'\"")
        return Path(first).name


def _unescape(value: str) -> str:
    # Freedesktop string escaping: \\, \s, \n, \t, \r (and \; inside lists).
    return (
        value.replace("\\s", " ")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_desktop_file(path: Path, locale: str = "") -> DesktopEntry | None:
    """Parse one .desktop file. Returns None for non-application entries.

    Never executes anything; a malformed file yields None, not an exception.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    in_group = False
    saw_group = False
    base: dict[str, str] = {}
    localized: dict[str, dict[str, str]] = {}
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_group = line[1:-1].strip() == _DESKTOP_GROUP
            saw_group = saw_group or in_group
            continue
        if not in_group or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        value = raw_value.strip()
        m = _LOCALE_SUFFIX.match(key)
        if not m:
            continue
        plain = m.group("key")
        if "[" in key:
            lang = key[key.index("[") + 1 : key.index("]")]
            localized.setdefault(lang, {})[plain] = _unescape(value)
        else:
            base[plain] = _unescape(value)

    # A valid desktop file requires the [Desktop Entry] group, Type and Name.
    if not saw_group or "Type" not in base or "Name" not in base:
        return None
    if base["Type"] != "Application":
        return None

    wanted_locale = locale.split(".", maxsplit=1)[0] if locale else ""
    lang_short = wanted_locale.split("_")[0]

    def pick(field: str) -> str:
        for cand in (wanted_locale, lang_short):
            if cand and cand in localized and field in localized[cand]:
                return localized[cand][field]
        return base.get(field, "")

    def listof(field: str) -> tuple[str, ...]:
        raw_v = base.get(field, "")
        if not raw_v:
            return ()
        return tuple(v for v in (_unescape(x) for x in _KEY_SPLIT.split(raw_v)) if v)

    def flag(field: str) -> bool:
        return base.get(field, "false").strip().lower() == "true"

    return DesktopEntry(
        path=path,
        desktop_id=path.name[: -len(".desktop")] if path.name.endswith(".desktop") else path.stem,
        name=pick("Name"),
        generic_name=pick("GenericName"),
        comment=pick("Comment"),
        exec_line=base.get("Exec", ""),
        icon=base.get("Icon", ""),
        categories=listof("Categories"),
        keywords=listof("Keywords"),
        mime_types=listof("MimeType"),
        startup_wm_class=base.get("StartupWMClass", ""),
        no_display=flag("NoDisplay"),
        hidden=flag("Hidden"),
        terminal=flag("Terminal"),
    )


@dataclass(frozen=True, slots=True)
class Identity:
    """All identifiers attributed to one installation instance."""

    package: PackageName
    desktop_ids: tuple[str, ...] = ()
    executables: tuple[str, ...] = ()
    icon_names: tuple[str, ...] = ()
    display_name: str = ""

    @property
    def candidate_names(self) -> frozenset[str]:
        """Normalized set of tokens used for leftover matching."""
        out: set[str] = {self.package.lower()}
        for did in self.desktop_ids:
            out.add(did.lower())
            tail = did.split(".")[-1]
            if tail:
                out.add(tail.lower())
        for exe in self.executables:
            out.add(exe.lower())
        return frozenset(out)


def identity_for_package(pkg: PackageRecord, root: Path = Path("/")) -> Identity:
    """Derive the Identity of one installed package from its file list."""
    desktop_files = [
        f for f in pkg.files if f.startswith("usr/share/applications/") and f.endswith(".desktop")
    ]
    entries: list[DesktopEntry] = []
    for rel in desktop_files:
        entry = parse_desktop_file(root / rel)
        if entry is not None:
            entries.append(entry)
    executables: list[str] = []
    for f in pkg.files:
        for prefix in _BIN_PREFIXES:
            if f.startswith(prefix) and "/" not in f[len(prefix) :]:
                executables.append(f[len(prefix) :])
    desktop_ids = tuple(e.desktop_id for e in entries)
    icons = tuple(e.icon for e in entries if e.icon)
    execs = tuple(sorted({*executables, *(e.exec_binary_guess for e in entries if e.exec_binary_guess)}))
    display = entries[0].name if entries else ""
    return Identity(
        package=pkg.name,
        desktop_ids=desktop_ids,
        executables=execs,
        icon_names=icons,
        display_name=display or pkg.name,
    )


def build_identity_index(
    packages: list[PackageRecord], root: Path = Path("/")
) -> dict[PackageName, Identity]:
    return {p.name: identity_for_package(p, root) for p in packages}
