"""Read-only integration tests against the live package database (§134).

These never write, never lock long-term, and never require root.
Skip when pyalpm or a pacman DB is absent (non-Arch CI hosts).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

pyalpm = pytest.importorskip("pyalpm")

if not os.path.isdir("/var/lib/pacman/local"):
    pytest.skip("no pacman database on this host", allow_module_level=True)

from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.identity import build_identity_index
from cachyuninstall.core.ownership import DictOwnerIndex, OwnershipOracle
from cachyuninstall.core.planner import RemovalPlanner


@pytest.fixture(scope="module")
def session() -> AlpmSession:
    s = AlpmSession()
    s.open()
    return s


def test_packages_enumerated(session: AlpmSession) -> None:
    packages = session.packages()
    assert len(packages) > 50, "expected a real system"
    names = {str(p.name) for p in packages}
    assert "glibc" in names
    assert "pacman" in names
    for p in packages:
        assert p.name and p.version
        assert p.origin.value in {
            "official",
            "cachyos",
            "other_repo",
            "foreign",
            "unknown",
        }


def test_ownership_lookup(session: AlpmSession) -> None:
    owners = session.file_owners("/usr/bin/pacman")
    assert "pacman" in owners


def test_planner_never_blocks_all_packages(session: AlpmSession) -> None:
    planner = RemovalPlanner(session.packages())
    # glibc must be blocked by *something* — it is required by ~everything.
    from cachyuninstall.core.errors import DependencyBlocked
    from cachyuninstall.core.models import PackageName

    with pytest.raises(DependencyBlocked):
        planner.build_plan(
            [PackageName("glibc")],
            also_remove_new_orphans=False,
            generation=session.generation(),
        )


def test_identity_index_builds(session: AlpmSession) -> None:
    packages = session.packages()[:120]
    index = build_identity_index(packages)
    assert len(index) == len(packages)
    assert all(ident.package for ident in index.values())


def test_owner_index_consistent(session: AlpmSession) -> None:
    oracle = OwnershipOracle(DictOwnerIndex(session.refresh_owner_index()))
    owners = oracle.package_owners("usr/bin/pacman")
    assert "pacman" in owners
