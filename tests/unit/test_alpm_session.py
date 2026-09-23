"""AlpmSession mapping tests over the fake handle (origin classification etc.)."""

from __future__ import annotations

from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.models import InstallReason, Origin, PackageName
from tests.harness.fake_alpm import (
    fake_handle_factory,
    world_foreign,
    world_modified_config,
    world_orphan_chain,
    world_single,
)


def _session(world, sync_map=None) -> AlpmSession:
    s = AlpmSession(handle_factory=fake_handle_factory(world, sync_map))
    return s


def test_enumeration_maps_records() -> None:
    world = world_single()
    session = _session(world)
    session.open()
    packages = session.packages()
    assert [p.name for p in packages] == [PackageName("solo")]
    rec = packages[0]
    assert rec.version == "1.0-1"
    assert rec.reason is InstallReason.EXPLICIT
    assert rec.files == ("usr/bin/solo",)


def test_foreign_when_not_in_sync_dbs() -> None:
    world = world_foreign()
    session = _session(world, sync_map={"extra": []})
    session.open()
    assert session.packages()[0].origin is Origin.FOREIGN


def test_cachyos_repo_classification() -> None:
    world = world_single()
    session = _session(world, sync_map={"cachyos": ["solo"]})
    session.open()
    rec = session.packages()[0]
    assert rec.origin is Origin.CACHYOS
    assert rec.repository == "cachyos"


def test_official_classification() -> None:
    world = world_single()
    session = _session(world)
    session.open()
    assert session.packages()[0].origin is Origin.OFFICIAL


def test_dependency_reason_mapped() -> None:
    world = world_orphan_chain()
    session = _session(world)
    session.open()
    by_name = {p.name: p for p in session.packages()}
    assert by_name[PackageName("mid")].reason is InstallReason.DEPENDENCY
    assert by_name[PackageName("app-c")].reason is InstallReason.EXPLICIT
    assert by_name[PackageName("mid")].required_by == ("app-c",)


def test_orphans_filter() -> None:
    world = world_orphan_chain()
    session = _session(world)
    session.open()
    assert session.orphans() == []  # mid needs app-c, leaf needs mid

    # if app-c is removed, mid and leaf become orphans (planner logic, tested
    # in test_planner); the static view must respect required_by:
    from cachyuninstall.core.models import InstallReason
    from tests.harness.fake_alpm import make_record

    world_post = [
        make_record("mid", reason=InstallReason.DEPENDENCY, depends=("leaf",)),
        make_record("leaf", reason=InstallReason.DEPENDENCY),
    ]
    session2 = _session(world_post)
    session2.open()
    assert {p.name for p in session2.orphans()} == {PackageName("mid"), PackageName("leaf")}


def test_owner_index_from_files() -> None:
    world = world_modified_config()
    session = _session(world)
    session.open()
    owners = session.file_owners("/etc/confapp.conf")
    assert owners == (PackageName("confapp"),)
    assert session.file_owners("/etc/other.conf") == ()


def test_generation_marker(tmp_path) -> None:
    world = world_single()
    session = _session(world)
    generation = session.generation()
    assert generation > 0


def test_light_enumeration_marks_unknown_and_skips_detail() -> None:
    world = world_orphan_chain()
    session = _session(world)
    session.open()
    rows = session.packages(with_origin_resolution=False, full_detail=False)
    assert rows, "light enumeration still lists packages"
    for rec in rows:
        assert rec.origin is Origin.UNKNOWN
        assert rec.files == ()
        assert rec.required_by == ()
        assert rec.depends == rec.depends  # name/version preserved
    by_name = {r.name: r for r in rows}
    assert by_name[PackageName("app-c")].depends == ("mid",)  # forward deps stay


def test_full_detail_restores_files_and_required_by() -> None:
    world = world_orphan_chain()
    session = _session(world)
    session.open()
    rows = session.packages(with_origin_resolution=False, full_detail=True)
    by_name = {r.name: r for r in rows}
    assert by_name[PackageName("mid")].required_by == (PackageName("app-c"),)
