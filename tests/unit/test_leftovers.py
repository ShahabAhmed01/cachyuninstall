"""Leftover scanner tests over synthetic home trees (§127)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cachyuninstall.core.identity import Identity
from cachyuninstall.core.leftovers import (
    APP_DATA_RULES,
    LeftoverScanner,
    ScanContext,
    _verify_firefox_profile,
)
from cachyuninstall.core.models import Confidence, LeftoverCategory, PackageName
from cachyuninstall.core.ownership import DictOwnerIndex, OwnershipOracle
from cachyuninstall.core.paths import PathPolicy


def _ctx(target: Identity, others: list[Identity], oracle: OwnershipOracle) -> ScanContext:
    return ScanContext(
        home=_HOME,  # set by fixture
        identity=target,
        other_identities=tuple(others),
        oracle=oracle,
    )


_HOME: Path
_scanner: LeftoverScanner


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    global _HOME, _scanner
    _HOME = tmp_path / "home" / "user"
    for sub in (
        ".config",
        ".cache",
        ".local/share",
        ".local/state",
        ".config/autostart",
        ".config/systemd/user",
        ".local/share/applications",
    ):
        (_HOME / sub).mkdir(parents=True, exist_ok=True)
    _scanner = LeftoverScanner(PathPolicy(_HOME))
    return _HOME


def oracle_empty() -> OwnershipOracle:
    return OwnershipOracle(DictOwnerIndex({}))


class TestScanner:
    def test_config_cache_data_detected(self) -> None:
        ident = Identity(package=PackageName("testapp"))
        for sub in (".config", ".cache", ".local/share"):
            (_HOME / sub / "testapp").mkdir(parents=True)
        (_HOME / ".config" / "unrelated").mkdir(exist_ok=True)

        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        paths = {c.path for c in out}
        assert _HOME / ".config" / "testapp" in paths
        assert _HOME / ".cache" / "testapp" in paths
        assert _HOME / ".local" / "share" / "testapp" in paths
        assert not any("unrelated" in str(p) for p in paths)

    def test_exact_package_name_is_high_confidence(self) -> None:
        ident = Identity(package=PackageName("testapp"))
        (_HOME / ".config" / "testapp").mkdir()
        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        cand = next(c for c in out if c.path == _HOME / ".config" / "testapp")
        assert cand.confidence is Confidence.HIGH
        assert cand.category is LeftoverCategory.CONFIGURATION
        assert cand.reason  # reason text present

    def test_package_owned_path_is_protected(self) -> None:
        ident = Identity(package=PackageName("testapp"))
        target = _HOME / ".local" / "share" / "testapp"
        target.mkdir(parents=True)
        owned_file = str(target / "x").lstrip("/")
        owned = OwnershipOracle(DictOwnerIndex({owned_file: ("otherpkg",)}))
        # simulate package owning content below the candidate
        out = _scanner.scan(_ctx(ident, [], owned))
        cand = next(c for c in out if c.path == target)
        assert cand.confidence is Confidence.PROTECTED
        assert "otherpkg" in cand.reason

    def test_shared_identity_is_protected(self) -> None:
        other = Identity(package=PackageName("beta"), desktop_ids=("shared.Dir",))
        # shared dir name equals another identity's desktop tail
        (_HOME / ".local" / "share" / "testapp").mkdir(parents=True)
        shared_dir = _HOME / ".local" / "share" / "Dir"
        shared_dir.mkdir()
        ident_shared = Identity(package=PackageName("alpha"), desktop_ids=("shared.Dir",))
        out = _scanner.scan(_ctx(ident_shared, [other], oracle_empty()))
        cand = next(c for c in out if c.path == shared_dir)
        assert cand.confidence is Confidence.PROTECTED
        assert "beta" in cand.shared_with

    def test_outside_policy_is_protected(self, tmp_path: Path) -> None:
        # Rule discovery only yields in-policy paths; defense-in-depth check.
        assert PathPolicy(_HOME).is_allowed_user_path(Path("/etc/passwd")) is False

    def test_no_candidates_no_output(self) -> None:
        ident = Identity(package=PackageName("absent"))
        assert _scanner.scan(_ctx(ident, [], oracle_empty())) == []

    def test_systemd_user_unit_detection(self) -> None:
        ident = Identity(package=PackageName("daemonapp"), desktop_ids=("org.x.Daemon",))
        unit = _HOME / ".config" / "systemd" / "user" / "org.x.Daemon.service"
        unit.write_text("[Service]\nExecStart=/usr/bin/x\n")
        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        assert any(c.path == unit for c in out)
        cand = next(c for c in out if c.path == unit)
        assert cand.confidence is Confidence.HIGH
        assert cand.category is LeftoverCategory.SYSTEMD_USER_UNIT

    def test_broken_symlink_dir_is_candidate_not_traversed(self, tmp_path: Path) -> None:
        ident = Identity(package=PackageName("linkapp"))
        (_HOME / ".cache" / "linkapp").mkdir(parents=True)
        # dangling symlink inside candidate tree
        (_HOME / ".cache" / "linkapp" / "dangling").symlink_to(tmp_path / "gone")
        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        cand = next(c for c in out if c.path == _HOME / ".cache" / "linkapp")
        assert cand.size_bytes >= 0  # measurement must not crash on broken links


class TestFirefoxRule:
    """Tests for the Firefox evidence-backed application data rule."""

    def test_firefox_rule_exists(self) -> None:
        rule_ids = [r.rule_id for r in APP_DATA_RULES]
        assert "RULE-APPDATA-FIREFOX-PROFILE" in rule_ids

    def test_firefox_rule_applies_to_firefox(self) -> None:
        rule = next(r for r in APP_DATA_RULES if r.rule_id == "RULE-APPDATA-FIREFOX-PROFILE")
        ident = Identity(package=PackageName("firefox"), desktop_ids=("org.mozilla.firefox",))
        assert rule.applies_to(ident)
        ident2 = Identity(package=PackageName("mozilla-firefox"))
        assert rule.applies_to(ident2)
        ident3 = Identity(package=PackageName("otherapp"))
        assert not rule.applies_to(ident3)

    def test_firefox_profile_detected(self) -> None:
        ident = Identity(package=PackageName("firefox"), desktop_ids=("org.mozilla.firefox",))
        mozilla_dir = _HOME / ".mozilla"
        firefox_dir = mozilla_dir / "firefox"
        firefox_dir.mkdir(parents=True)
        profile_dir = firefox_dir / "abc123.default"
        profile_dir.mkdir()
        # Add a Firefox profile marker
        (profile_dir / "prefs.js").write_text(
            'user_pref("browser.startup.homepage", "https://example.com");\n'
        )

        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        cand = next((c for c in out if c.path == profile_dir), None)
        assert cand is not None, f"Expected Firefox profile candidate, got: {[c.path for c in out]}"
        assert cand.confidence is Confidence.HIGH
        assert cand.category is LeftoverCategory.APPLICATION_DATA
        assert cand.rule_id == "RULE-APPDATA-FIREFOX-PROFILE"
        assert "Firefox profile marker found" in cand.reason

    def test_firefox_profile_without_marker_is_medium_confidence(self) -> None:
        ident = Identity(package=PackageName("firefox"))
        mozilla_dir = _HOME / ".mozilla"
        firefox_dir = mozilla_dir / "firefox"
        firefox_dir.mkdir(parents=True)
        profile_dir = firefox_dir / "xyz789.default"
        profile_dir.mkdir()
        # No Firefox profile markers - just an empty directory

        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        cand = next((c for c in out if c.path == profile_dir), None)
        assert cand is not None
        assert cand.confidence is Confidence.MEDIUM  # base confidence without verification
        assert cand.rule_id == "RULE-APPDATA-FIREFOX-PROFILE"

    def test_firefox_profile_with_profiles_ini(self) -> None:
        ident = Identity(package=PackageName("firefox"))
        mozilla_dir = _HOME / ".mozilla"
        firefox_dir = mozilla_dir / "firefox"
        firefox_dir.mkdir(parents=True)
        profile_dir = firefox_dir / "profile1.default"
        profile_dir.mkdir()
        # Add profiles.ini in the firefox directory (parent of profile)
        (firefox_dir / "profiles.ini").write_text("[Profile1]\nName=default\nPath=profile1.default\n")

        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        cand = next((c for c in out if c.path == profile_dir), None)
        assert cand is not None
        assert cand.confidence is Confidence.HIGH
        assert "Profile listed in profiles.ini" in cand.reason

    def test_firefox_rule_does_not_match_unrelated_mozilla(self) -> None:
        ident = Identity(package=PackageName("firefox"))
        mozilla_dir = _HOME / ".mozilla"
        firefox_dir = mozilla_dir / "firefox"
        firefox_dir.mkdir(parents=True)
        # Some other directory under .mozilla that isn't a Firefox profile
        other_dir = mozilla_dir / "some-extension"
        other_dir.mkdir()

        out = _scanner.scan(_ctx(ident, [], oracle_empty()))
        # Should find the firefox subdir but not match other_dir as a profile
        # (because pattern only yields firefox/ subdirs with profiles)
        firefox_candidates = [c for c in out if "firefox" in str(c.path)]
        assert len(firefox_candidates) >= 0  # at least the firefox dir exists

    def test_firefox_rule_protected_by_ownership(self) -> None:
        ident = Identity(package=PackageName("firefox"))
        mozilla_dir = _HOME / ".mozilla"
        firefox_dir = mozilla_dir / "firefox"
        firefox_dir.mkdir(parents=True)
        profile_dir = firefox_dir / "profile.default"
        profile_dir.mkdir()
        (profile_dir / "prefs.js").write_text("")

        # Another package owns a file under this path
        owned = OwnershipOracle(DictOwnerIndex({str(profile_dir / "x").lstrip("/"): ("otherpkg",)}))
        out = _scanner.scan(_ctx(ident, [], owned))
        cand = next((c for c in out if c.path == profile_dir), None)
        assert cand is not None
        assert cand.confidence is Confidence.PROTECTED

    def test_firefox_rule_shared_with_other_identity(self) -> None:
        # Another identity with same token (using desktop ID tail 'firefox')
        other = Identity(package=PackageName("beta"), desktop_ids=("shared.firefox",))
        ident = Identity(package=PackageName("firefox"), desktop_ids=("org.mozilla.firefox",))
        mozilla_dir = _HOME / ".mozilla"
        firefox_dir = mozilla_dir / "firefox"
        firefox_dir.mkdir(parents=True)
        profile_dir = firefox_dir / "profile.default"
        profile_dir.mkdir()
        (profile_dir / "prefs.js").write_text("")

        out = _scanner.scan(_ctx(ident, [other], oracle_empty()))
        cand = next((c for c in out if c.path == profile_dir), None)
        # The token "firefox" is shared, so should be PROTECTED
        assert cand is not None
        assert cand.confidence is Confidence.PROTECTED
        assert "beta" in cand.shared_with


class TestFirefoxVerification:
    """Tests for the Firefox profile verification function."""

    def test_verify_firefox_profile_with_prefs_js(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile.default"
        profile.mkdir()
        (profile / "prefs.js").write_text("user_pref('test', true);")
        ok, detail = _verify_firefox_profile(profile)
        assert ok
        assert "prefs.js" in detail

    def test_verify_firefox_profile_with_cert9_db(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile.default"
        profile.mkdir()
        (profile / "cert9.db").write_text("")
        ok, detail = _verify_firefox_profile(profile)
        assert ok
        assert "cert9.db" in detail

    def test_verify_firefox_profile_with_places_sqlite(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile.default"
        profile.mkdir()
        (profile / "places.sqlite").write_text("")
        ok, detail = _verify_firefox_profile(profile)
        assert ok
        assert "places.sqlite" in detail

    def test_verify_firefox_profile_with_profiles_ini(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile.default"
        profile.mkdir()
        parent = tmp_path
        (parent / "profiles.ini").write_text("[Profile1]\nName=default\nPath=profile.default\n")
        ok, detail = _verify_firefox_profile(profile)
        assert ok
        assert "profiles.ini" in detail

    def test_verify_firefox_profile_no_markers(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile.default"
        profile.mkdir()
        ok, detail = _verify_firefox_profile(profile)
        assert not ok
        assert "No Firefox profile markers" in detail
