"""Removal planning — pure domain logic over package metadata.

Given removal targets, produces a RemovalImpact describing:
  * what is blocked (other installed packages require a target) — never
    silently cascaded;
  * which dependencies would become true orphans *as a consequence of this
    removal* (offered as an explicit, separate user choice);
  * which dependencies are shared and therefore kept.

This module never touches pyalpm or the filesystem; it is fully testable on
synthetic package worlds.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from cachyuninstall.core.errors import DependencyBlocked, PackageNotFound
from cachyuninstall.core.models import (
    InstallReason,
    LeftoverCandidate,
    PackageName,
    PackageRecord,
    ProviderKind,
    RemovalImpact,
    RemovalPlan,
)

_DEP_CONSTRAINT = re.compile(r"[<>=]")


def dep_base_name(depstring: str) -> str:
    """'gtk4>=1:4.12' -> 'gtk4'; 'libfoo.so=1-64' -> 'libfoo.so'."""
    return _DEP_CONSTRAINT.split(depstring, maxsplit=1)[0].strip()


@dataclass(frozen=True, slots=True)
class PackageSet:
    """Indexed view over a package snapshot, resolving virtual provides."""

    by_name: dict[PackageName, PackageRecord]
    _provides: dict[str, PackageName]  # provide-token -> concrete package

    @staticmethod
    def from_list(packages: list[PackageRecord]) -> PackageSet:
        by_name = {p.name: p for p in packages}
        provides: dict[str, PackageName] = {}
        for p in packages:
            for prov in p.provides:
                token = dep_base_name(prov)
                # First provider wins deterministically; real ambiguity is rare
                # and never safety-critical (worse case: shown as kept shared).
                provides.setdefault(token, p.name)
        return PackageSet(by_name=by_name, _provides=provides)

    def get(self, name: str) -> PackageRecord | None:
        direct = self.by_name.get(PackageName(name))
        if direct is not None:
            return direct
        provider = self._provides.get(name)
        return self.by_name.get(provider) if provider is not None else None


class RemovalPlanner:
    def __init__(self, packages: list[PackageRecord]) -> None:
        self._set = PackageSet.from_list(packages)

    def analyze(self, targets: list[PackageName]) -> RemovalImpact:
        missing = [t for t in targets if self._set.get(t) is None]
        if missing:
            raise PackageNotFound("Package not installed: " + ", ".join(sorted(map(str, missing))))
        target_set = frozenset(targets)

        blocked: dict[PackageName, tuple[PackageName, ...]] = {}
        for target in targets:
            pkg = self._set.by_name[target]
            external = tuple(sorted(PackageName(r) for r in pkg.required_by if r not in target_set))
            if external:
                blocked[target] = external

        new_orphans = tuple(sorted(self._orphans_after(target_set) - target_set))
        kept_shared: dict[PackageName, tuple[PackageName, ...]] = {}
        for target in targets:
            pkg = self._set.by_name[target]
            for depstring in pkg.depends:
                dep = self._set.get(dep_base_name(depstring))
                if dep is None or dep.name in target_set:
                    continue
                others = tuple(
                    sorted(PackageName(r) for r in dep.required_by if r not in target_set and r != target)
                )
                if others and dep.name not in new_orphans:
                    kept_shared[dep.name] = others

        return RemovalImpact(
            requested=tuple(targets),
            blocked_by=blocked,
            new_orphans=tuple(PackageName(o) for o in new_orphans),
            kept_shared=kept_shared,
        )

    def build_plan(
        self,
        targets: list[PackageName],
        *,
        also_remove_new_orphans: bool,
        generation: int,
        leftovers: tuple[LeftoverCandidate, ...] = (),
    ) -> RemovalPlan:
        """Validate and freeze a plan. Raises DependencyBlocked when required."""
        impact = self.analyze(targets)
        if impact.blocked_by:
            blockers = tuple(sorted({b for group in impact.blocked_by.values() for b in group}))
            raise DependencyBlocked(
                "Other installed packages require the selected package(s).",
                blockers=blockers,
            )
        cascade = impact.new_orphans if also_remove_new_orphans else ()
        warnings: list[str] = []
        for name, users in impact.kept_shared.items():
            users_s = ", ".join(map(str, users[:3]))
            warnings.append(f"{name} is kept — required by {users_s}.")
        return RemovalPlan(
            plan_id=str(uuid.uuid4()),
            provider=ProviderKind.PACMAN,
            targets=tuple(targets),
            cascade=tuple(PackageName(c) for c in cascade),
            system_generation=generation,
            leftover_candidates=leftovers,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------ simulation
    def _orphans_after(self, removal: frozenset[PackageName]) -> set[PackageName]:
        """Packages that become orphans if `removal` happens.

        Iterates to a fixpoint so transitive leaves are found. Only considers
        packages installed as dependencies, and treats reverse-dependency
        membership in `removal` as 'no longer required'.
        """
        removed: set[PackageName] = set(removal)
        changed = True
        while changed:
            changed = False
            frontier = list(removed)
            for name in frontier:
                pkg = self._set.by_name.get(name)
                if pkg is None:
                    continue
                for depstring in pkg.depends:
                    dep = self._set.get(dep_base_name(depstring))
                    if dep is None or dep.name in removed:
                        continue
                    if dep.reason is not InstallReason.DEPENDENCY:
                        continue
                    remaining_users = [r for r in dep.required_by if r not in removed]
                    if not remaining_users:
                        removed.add(dep.name)
                        changed = True
        return removed
