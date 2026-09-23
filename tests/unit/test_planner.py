"""Planner tests over the package worlds of §126."""

from __future__ import annotations

import pytest

from cachyuninstall.core.errors import DependencyBlocked, PackageNotFound
from cachyuninstall.core.models import PackageName
from cachyuninstall.core.planner import RemovalPlanner, dep_base_name
from tests.harness.fake_alpm import (
    world_blocked,
    world_orphan_chain,
    world_shared_dep,
    world_single,
)


def test_dep_base_name_strips_constraints() -> None:
    assert dep_base_name("gtk4>=1:4.12") == "gtk4"
    assert dep_base_name("libfoo.so=1-64") == "libfoo.so"
    assert dep_base_name("plain") == "plain"
    assert dep_base_name("python>=3.11") == "python"


def test_world_single_no_dependencies() -> None:
    impact = RemovalPlanner(world_single()).analyze([PackageName("solo")])
    assert impact.blocked_by == {}
    assert impact.new_orphans == ()
    assert impact.kept_shared == {}


def test_world_shared_dependency_is_kept() -> None:
    impact = RemovalPlanner(world_shared_dep()).analyze([PackageName("app-a")])
    assert impact.blocked_by == {}
    assert "shared-lib" in map(str, impact.kept_shared.keys())
    assert "app-b" in map(str, impact.kept_shared[PackageName("shared-lib")])
    assert "shared-lib" not in map(str, impact.new_orphans)


def test_world_orphan_chain_cascades_only_when_requested() -> None:
    planner = RemovalPlanner(world_orphan_chain())
    plan_no = planner.build_plan([PackageName("app-c")], also_remove_new_orphans=False, generation=1)
    assert plan_no.cascade == ()
    plan_yes = planner.build_plan([PackageName("app-c")], also_remove_new_orphans=True, generation=1)
    assert set(map(str, plan_yes.cascade)) == {"mid", "leaf"}


def test_world_blocked_raises_with_blockers() -> None:
    planner = RemovalPlanner(world_blocked())
    with pytest.raises(DependencyBlocked) as exc_info:
        planner.build_plan([PackageName("victim")], also_remove_new_orphans=False, generation=1)
    assert "keeper" in map(str, exc_info.value.blockers)


def test_unknown_package_raises() -> None:
    planner = RemovalPlanner(world_single())
    with pytest.raises(PackageNotFound):
        planner.analyze([PackageName("does-not-exist")])


def test_plan_digest_stable() -> None:
    planner = RemovalPlanner(world_single())
    p1 = planner.build_plan([PackageName("solo")], also_remove_new_orphans=False, generation=42)
    p2 = planner.build_plan([PackageName("solo")], also_remove_new_orphans=False, generation=42)
    assert p1.digest() == p2.digest()
    p3 = planner.build_plan([PackageName("solo")], also_remove_new_orphans=False, generation=43)
    assert p1.digest() != p3.digest()


def test_explicit_dependency_not_orphaned() -> None:
    # shared-lib is dependency-installed; app removal leaves it orphaned only
    # when nothing else needs it — app-b still does.
    planner = RemovalPlanner(world_shared_dep())
    impact = planner.analyze([PackageName("app-a")])
    assert PackageName("shared-lib") not in impact.new_orphans


def test_batch_removal_between_targets() -> None:
    # Removing both members of a dependency pair at once stays unblocked.
    planner = RemovalPlanner(world_blocked())
    plan = planner.build_plan(
        [PackageName("victim"), PackageName("keeper")],
        also_remove_new_orphans=False,
        generation=7,
    )
    assert set(map(str, plan.targets)) == {"victim", "keeper"}
