"""Ownership oracle: the last word on whether a path may be touched.

Rule (§47): if ANY installed package owns a path, the path is protected —
no heuristic may override this. A second axis protects against *application*
level sharing: when another installed application's identity also matches a
candidate token, the candidate is downgraded/protected unless the user
explicitly inspects it.
"""

from __future__ import annotations

from typing import Protocol

from cachyuninstall.core.models import PackageName


class OwnerIndex(Protocol):
    """Read-only file→packages index over the local package database."""

    def owners_of_file(self, relpath: str) -> tuple[PackageName, ...]: ...
    def packages_with_files_under(self, relprefix: str) -> tuple[PackageName, ...]: ...


class DictOwnerIndex:
    """In-memory index built from a full local-DB file listing."""

    def __init__(self, mapping: dict[str, tuple[str, ...]]) -> None:
        # Keys are db-relative paths without leading '/', e.g. "usr/bin/foo".
        self._map: dict[str, tuple[str, ...]] = dict(mapping)
        prefixes: dict[str, list[str]] = {}
        for key, owners in mapping.items():
            parts = key.split("/")
            for i in range(1, len(parts) + 1):
                bucket = prefixes.setdefault("/".join(parts[:i]), [])
                for owner in owners:
                    if owner not in bucket:
                        bucket.append(owner)
        self._prefix: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in prefixes.items()}

    def owners_of_file(self, relpath: str) -> tuple[PackageName, ...]:
        return tuple(PackageName(o) for o in self._map.get(relpath.lstrip("/"), ()))

    def packages_with_files_under(self, relprefix: str) -> tuple[PackageName, ...]:
        return tuple(PackageName(o) for o in self._prefix.get(relprefix.lstrip("/").rstrip("/"), ()))


class OwnershipOracle:
    """Combines the package index with identity-level sharing knowledge."""

    def __init__(self, index: OwnerIndex) -> None:
        self._index = index

    def package_owners(self, absolute_path: str) -> tuple[PackageName, ...]:
        return self._index.owners_of_file(absolute_path)

    def package_claims_below(self, absolute_path: str) -> tuple[PackageName, ...]:
        return self._index.packages_with_files_under(absolute_path)
