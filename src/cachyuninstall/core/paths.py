"""Central path-safety policy.

Every deletion candidate — from any rule, provider or UI path — MUST pass
through this module twice: at scan time and again immediately before any
unlink/rmdir. Nothing else in the codebase decides whether a path is safe.

Design:
  * allowlist (user-writable XDG zones), never "blocklist-only";
  * no symlink traversal: identity is established with O_NOFOLLOW and
    dev+ino comparison, so a candidate swapped for a symlink between scan
    and delete fails closed (FileChanged);
  * system locations are out of scope by construction: the only way system
    files are removed is through libalpm transactions, never via this module.
"""

from __future__ import annotations

import os
import stat as statmod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cachyuninstall.core.errors import FileChanged, PathProtected

# Hard-rejected top-level anchors. A candidate equal to, or containing any of
# these as a non-final component outside the user's home, is refused.
_SYSTEM_ANCHORS: tuple[str, ...] = (
    "/",
    "/boot",
    "/efi",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/var",
    "/home",
    "/root",
    "/opt",
    "/srv",
    "/dev",
    "/proc",
    "/sys",
    "/run",
    "/mnt",
    "/media",
    "/tmp",  # noqa: S108 - this is a DENY-list entry, not a usage of /tmp
)

# Inside $HOME, these are the only trees from which candidates may be deleted.
# .mozilla is included for Firefox/Thunderbird profile data (well-known location).
_USER_ALLOWED_SUBTREES: tuple[str, ...] = (
    ".config",
    ".cache",
    ".local/share",
    ".local/state",
    ".config/autostart",
    ".config/systemd/user",
    ".mozilla",
)

# Even inside allowed subtrees these specific homes are protected (they hold
# the state of CachyUninstall itself and of desktop/session plumbing that must
# never be removed as "leftovers").
_PROTECTED_BASENAMES: tuple[str, ...] = (
    "cachyuninstall",
    "fontconfig",
    "dconf",
    "gnupg",
    "kwalletd",
    "kwallet",
    "plasma-workspace",
    "systemd",
)


class PathVerdict(Enum):
    ALLOWED_USER = "allowed_user"
    PROTECTED_SYSTEM = "protected_system"
    PROTECTED_NAME = "protected_name"
    OUTSIDE_USER_AREA = "outside_user_area"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Scan-time identity of a filesystem object; compared again at delete."""

    path: Path
    dev: int
    ino: int
    kind: str  # "dir" | "file" | "symlink"

    @staticmethod
    def capture(path: Path) -> FileIdentity:
        st = os.lstat(path)
        if statmod.S_ISDIR(st.st_mode):
            kind = "dir"
        elif statmod.S_ISLNK(st.st_mode):
            kind = "symlink"
        else:
            kind = "file"
        return FileIdentity(path=path, dev=st.st_dev, ino=st.st_ino, kind=kind)


class PathPolicy:
    """Decides which user-writable locations cleanup may touch."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = (home or Path.home()).resolve()

    # ------------------------------------------------------------------ roots
    def allowed_user_roots(self) -> tuple[Path, ...]:
        return tuple(self.home / sub for sub in _USER_ALLOWED_SUBTREES)

    # ---------------------------------------------------------------- verdict
    def classify(self, path: Path) -> PathVerdict:
        """Pure classification; never raises, never touches the filesystem."""
        if not path.is_absolute():
            # Relative candidates are never trusted.
            return PathVerdict.PROTECTED_SYSTEM
        text = str(path)
        for anchor in _SYSTEM_ANCHORS:
            if (text == anchor or text.startswith(anchor + "/")) and not self._inside_home(path):
                return PathVerdict.PROTECTED_SYSTEM
        if not self._under_allowed(path):
            return PathVerdict.OUTSIDE_USER_AREA
        if self._hits_protected_name(path):
            return PathVerdict.PROTECTED_NAME
        return PathVerdict.ALLOWED_USER

    def is_allowed_user_path(self, path: Path) -> bool:
        return self.classify(path) is PathVerdict.ALLOWED_USER

    def require_allowed(self, path: Path) -> None:
        verdict = self.classify(path)
        if verdict is not PathVerdict.ALLOWED_USER:
            raise PathProtected(f"Path refused by policy: {path} ({verdict.value})", detail=str(path))

    # ---------------------------------------------------------------- checkers
    def _inside_home(self, path: Path) -> bool:
        try:
            path.relative_to(self.home)
            return True
        except ValueError:
            return False

    def _under_allowed(self, path: Path) -> bool:
        # Resolve the *parent* to neutralize ".."; the candidate itself is not
        # required to exist.
        try:
            resolved_parent = path.parent.resolve(strict=False)
        except OSError:
            return False
        for root in self.allowed_user_roots():
            try:
                resolved_parent.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _hits_protected_name(self, path: Path) -> bool:
        parts = path.parts
        return any(part in _PROTECTED_BASENAMES for part in parts[-2:])


# --------------------------------------------------------------------------
# Execution-time safe deletion primitives (used by core/filesystem.py).
# --------------------------------------------------------------------------


def open_parent_nofollow(path: Path) -> tuple[int, str]:
    """Open `path`'s parent dirfd and return (dirfd, basename).

    Raises PathProtected if any *parent* component is a symlink pointing
    outside the allowed set — resolution happens before policy use.
    """
    parent = path.parent
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(str(parent), flags)
    except OSError as exc:
        raise PathProtected(f"Cannot open parent safely: {parent}", detail=str(exc)) from exc
    return fd, path.name


def verify_identity(fd_dir: int, name: str, expected: FileIdentity) -> None:
    """Compare the live object under dirfd with the scan-time identity."""
    try:
        st = os.stat(name, dir_fd=fd_dir, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise FileChanged(f"Already gone: {expected.path}") from exc
    if (st.st_dev, st.st_ino) != (expected.dev, expected.ino):
        raise FileChanged(
            f"Object changed since scan: {expected.path}", detail=f"dev/ino mismatch for {expected.path}"
        )


def delete_tree_fd(fd_parent: int, name: str, expected: FileIdentity) -> tuple[int, list[Path]]:
    """Recursively delete `name` under open dirfd. Never follows symlinks.

    Returns (bytes_freed, deleted_paths). Raises FileChanged/PathProtected on
    any identity mismatch — fail closed, leave the rest untouched.
    """
    verify_identity(fd_parent, name, expected)
    freed, deleted = _delete_tree_inner(fd_parent, name, expected.path)
    return freed, deleted


def _delete_tree_inner(dirfd: int, name: str, display: Path) -> tuple[int, list[Path]]:
    st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    deleted: list[Path] = []
    freed = st.st_blocks * 512
    if statmod.S_ISDIR(st.st_mode) and not statmod.S_ISLNK(st.st_mode):
        childfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
        try:
            for entry in os.listdir(childfd):
                if entry in (".", ".."):
                    continue
                child_freed, child_deleted = _delete_tree_inner(childfd, entry, display / entry)
                freed += child_freed
                deleted.extend(child_deleted)
        finally:
            os.close(childfd)
        os.rmdir(name, dir_fd=dirfd)
    else:
        os.unlink(name, dir_fd=dirfd)
    deleted.append(display)
    return freed, deleted
