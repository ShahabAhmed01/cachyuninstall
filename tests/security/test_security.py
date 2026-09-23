"""Security tests (§129): traversal, symlink escape, injection, stale plans.

Each test maps to one threat-model entry in docs/SECURITY.md.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cachyuninstall.core.errors import FileChanged, PathProtected
from cachyuninstall.core.filesystem import CleanupExecutor
from cachyuninstall.core.identity import Identity, parse_desktop_file
from cachyuninstall.core.leftovers import LeftoverScanner, ScanContext
from cachyuninstall.core.models import (
    Confidence,
    LeftoverCandidate,
    LeftoverCategory,
    PackageName,
    ResultKind,
)
from cachyuninstall.core.ownership import DictOwnerIndex, OwnershipOracle
from cachyuninstall.core.paths import FileIdentity, PathPolicy


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home" / "user"
    for sub in (".config", ".cache", ".local/share", ".local/state"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    return home


class TestTraversal:
    def test_dotdot_candidate_refused(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        policy = PathPolicy(home)
        with pytest.raises(PathProtected):
            policy.require_allowed(home / ".config" / ".." / ".." / "etc" / "x")

    def test_root_candidate_refused(self, tmp_path: Path) -> None:
        policy = PathPolicy(_home(tmp_path))
        for target in ("/", "/etc", "/usr/bin", "/var/lib/pacman"):
            with pytest.raises(PathProtected):
                policy.require_allowed(Path(target))

    def test_protocol_sanitizes_pkg_names(self) -> None:
        # covered exhaustively in test_protocol; belt+braces entry point check:
        from cachyuninstall.privilege.protocol import decode_request, encode_request

        raw = encode_request(
            "remove_packages",
            {
                "plan_id": "x",
                "targets": ["good"],
                "cascade": [],
                "generation": 1,
                "digest": "0" * 64,
            },
        )
        _op, req = decode_request(raw)
        assert req is not None
        # injection payloads never survive decode:
        import json

        evil = json.loads(raw)
        evil["payload"]["targets"] = ["good; rm -rf /"]
        with pytest.raises(Exception):
            decode_request(json.dumps(evil))


class TestSymlinkEscape:
    def test_symlink_chain_into_etc_never_deleted(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        # Construct an attacker candidate: config dir that IS a symlink
        target_dir = tmp_path / "important"
        target_dir.mkdir()
        (target_dir / "data.txt").write_text("precious")
        link = home / ".config" / "evilapp"
        link.symlink_to(target_dir)

        policy = PathPolicy(home)
        policy.require_allowed(link)  # the link itself is in-policy…
        cand = LeftoverCandidate(
            path=link,
            category=LeftoverCategory.CONFIGURATION,
            confidence=Confidence.HIGH,
            rule_id="RULE-XDG-CONFIG",
            reason="test",
            size_bytes=0,
            owner_package=None,
        )
        report = CleanupExecutor(policy).execute([cand])
        assert report.kind in (ResultKind.SUCCESS, ResultKind.PARTIAL)
        assert not link.exists()
        assert (target_dir / "data.txt").exists(), "symlink target must survive"

    def test_swapped_symlink_aborts(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        real = home / ".config" / "swapapp"
        real.mkdir()
        identity = FileIdentity.capture(real)
        real.rmdir()
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        (decoy / "keep.txt").write_text("keep")
        os.symlink(decoy, real)  # TOCTOU: same path, different object

        from cachyuninstall.core.paths import delete_tree_fd, open_parent_nofollow

        fd, name = open_parent_nofollow(real)
        try:
            with pytest.raises(FileChanged):
                delete_tree_fd(fd, name, identity)
        finally:
            os.close(fd)
        assert (decoy / "keep.txt").exists()


class TestDesktopExecution:
    def test_exec_never_runs(self, tmp_path: Path) -> None:
        marker = tmp_path / "owned"
        entry = tmp_path / "org.evil.G.desktop"
        entry.write_text(f"[Desktop Entry]\nType=Application\nName=Ev\nExec=/bin/sh -c 'touch {marker}' %u\n")
        parsed = parse_desktop_file(entry)
        assert parsed is not None
        assert not marker.exists()


class TestOwnershipProtection:
    def test_owned_candidate_never_cleaned(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        ident = Identity(package=PackageName("victim.app"))
        cand_dir = home / ".local" / "share" / "victim.app"
        cand_dir.mkdir(parents=True)
        rel = str(cand_dir).lstrip("/")
        oracle = OwnershipOracle(DictOwnerIndex({rel + "/file.bin": ("ownerpkg",)}))
        scanner = LeftoverScanner(PathPolicy(home))
        ctx = ScanContext(home=home, identity=ident, other_identities=(), oracle=oracle)
        results = scanner.scan(ctx)
        cand = next(c for c in results if c.path == cand_dir)
        assert cand.confidence is Confidence.PROTECTED

        # Even if a bug slips it into a cleanup list, the executor refuses:
        report = CleanupExecutor(PathPolicy(home)).execute([cand])
        assert all(not i.ok for i in report.items)
        assert cand_dir.exists()


class TestStalePlan:
    def test_generation_drift_rejected(self) -> None:
        from cachyuninstall.privilege.helper import HelperCore
        from cachyuninstall.privilege.protocol import decode_reply, encode_request
        from tests.unit.test_helper_core import AllowAll, FakeBackend

        backend = FakeBackend({"pkg"}, generation=2)
        core = HelperCore(backend, AllowAll())
        raw = encode_request(
            "remove_packages",
            {
                "plan_id": "p",
                "targets": ["pkg"],
                "cascade": [],
                "generation": 1,
                "digest": "0" * 64,
            },
        )
        reply = decode_reply(core.handle(raw, ":1.7"))
        assert not reply.ok and reply.code == "stale-plan"
        assert backend.removed == []
