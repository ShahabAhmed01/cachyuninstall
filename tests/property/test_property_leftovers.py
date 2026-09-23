"""Hypothesis property tests (§128).

Critical invariant: the scanner must NEVER return a non-PROTECTED candidate
that the package database claims to own.
"""

from __future__ import annotations

import string

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from cachyuninstall.core.identity import Identity
from cachyuninstall.core.leftovers import LeftoverScanner, ScanContext
from cachyuninstall.core.models import Confidence, PackageName
from cachyuninstall.core.ownership import DictOwnerIndex, OwnershipOracle
from cachyuninstall.core.paths import PathPolicy

_TOKEN = st.text(alphabet=string.ascii_lowercase + "0123456789.-_", min_size=1, max_size=24)


@given(name=_TOKEN, other=_TOKEN)
@settings(max_examples=200, suppress_health_check=list(HealthCheck))
def test_owned_paths_always_protected(tmp_path_factory, name: str, other: str) -> None:
    base = tmp_path_factory.mktemp("h")
    home = base / "home" / "u"
    cfg = home / ".config" / name
    cfg.mkdir(parents=True, exist_ok=True)
    owned_marker = home / ".config" / other
    owned_marker.mkdir(parents=True, exist_ok=True)
    (owned_marker / "f").write_text("x")

    mapping = {
        f"{str(owned_marker).lstrip('/')}/f": ("pkg-owner",),
    }
    oracle = OwnershipOracle(DictOwnerIndex(mapping))
    ident = Identity(package=PackageName(other))
    scanner = LeftoverScanner(PathPolicy(home))
    results = scanner.scan(ScanContext(home=home, identity=ident, other_identities=(), oracle=oracle))
    for cand in results:
        if other in str(cand.path):
            assert cand.confidence is Confidence.PROTECTED
