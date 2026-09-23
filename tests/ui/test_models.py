"""Qt model/filter tests (offscreen)."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from cachyuninstall.core.models import Origin, ProviderKind
from cachyuninstall.providers.base import Installation
from cachyuninstall.ui.package_model import InstallationFilter, InstallationModel


def _rows() -> list[Installation]:
    return [
        Installation(
            instance_id="pacman:firefox",
            provider=ProviderKind.PACMAN,
            name="firefox",
            display_name="Firefox",
            version="131.0",
            origin=Origin.OFFICIAL,
            size_bytes=220_000_000,
            summary="Web browser",
            install_date=1700000000,
        ),
        Installation(
            instance_id="pacman:audacity",
            provider=ProviderKind.PACMAN,
            name="audacity",
            display_name="Audacity",
            version="3.6",
            origin=Origin.CACHYOS,
            size_bytes=95_000_000,
            summary="Audio editor",
            install_date=1700000000,
        ),
    ]


@pytest.fixture()
def model(qapp) -> tuple[InstallationModel, InstallationFilter]:
    m = InstallationModel()
    m.set_rows(_rows())
    f = InstallationFilter()
    f.setSourceModel(m)
    return m, f


def test_row_count(model) -> None:
    m, f = model
    assert m.rowCount() == 2
    assert f.rowCount() == 2


def test_search_filters_by_name(model) -> None:
    _m, f = model
    f.set_query("firefox")
    assert f.rowCount() == 1


def test_search_matches_summary(model) -> None:
    _m, f = model
    f.set_query("audio")
    assert f.rowCount() == 1


def test_origin_filter(model) -> None:
    _m, f = model
    f.set_origin_filter("cachyos")
    assert f.rowCount() == 1


def test_search_is_case_insensitive(model) -> None:
    _m, f = model
    f.set_query("FIREFOX")
    assert f.rowCount() == 1


def test_origin_unknown_renders_honestly(model) -> None:
    m, _f = model
    rows = _rows()
    rows.append(
        Installation(
            instance_id="pacman:pending",
            provider=ProviderKind.PACMAN,
            name="pending",
            display_name="pending",
            version="1.0",
            origin=Origin.UNKNOWN,
            size_bytes=1,
        )
    )
    m.set_rows(rows)
    idx = m.index(2, 2)
    assert m.data(idx) == "Unknown"
