"""Path-policy tests (§46)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cachyuninstall.core.errors import FileChanged
from cachyuninstall.core.paths import (
    FileIdentity,
    PathPolicy,
    PathVerdict,
    delete_tree_fd,
    open_parent_nofollow,
)


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home" / "user"
    for sub in (".config", ".cache", ".local/share", ".local/state"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    return home


class TestClassification:
    def test_allows_user_config(self, home: Path) -> None:
        policy = PathPolicy(home)
        assert policy.classify(home / ".config" / "firefox") is PathVerdict.ALLOWED_USER

    @pytest.mark.parametrize("target", ["/", "/etc", "/usr", "/var", "/home", "/boot", "/bin", "/lib64"])
    def test_rejects_system_dirs(self, home: Path, target: str) -> None:
        policy = PathPolicy(home)
        assert policy.classify(Path(target)) is PathVerdict.PROTECTED_SYSTEM

    def test_rejects_other_home(self, home: Path) -> None:
        policy = PathPolicy(home)
        assert policy.classify(Path("/home/other/.config/x")) is PathVerdict.PROTECTED_SYSTEM

    def test_rejects_home_root(self, home: Path) -> None:
        policy = PathPolicy(home)
        assert policy.classify(home) is PathVerdict.OUTSIDE_USER_AREA

    def test_rejects_random_user_dir(self, home: Path) -> None:
        policy = PathPolicy(home)
        assert policy.classify(home / "Documents" / "x") is PathVerdict.OUTSIDE_USER_AREA

    def test_rejects_protected_app_state(self, home: Path) -> None:
        (home / ".config" / "cachyuninstall").mkdir(parents=True)
        policy = PathPolicy(home)
        assert policy.classify(home / ".config" / "cachyuninstall") is PathVerdict.PROTECTED_NAME

    def test_relative_paths_rejected(self, home: Path) -> None:
        policy = PathPolicy(home)
        assert policy.classify(Path(".config/foo")) is PathVerdict.PROTECTED_SYSTEM

    def test_dotdot_escape_resolved(self, home: Path) -> None:
        policy = PathPolicy(home)
        # ../.. escape out of .config must not classify as user data.
        evil = home / ".config" / ".." / ".." / "secrets"
        assert policy.classify(evil) is PathVerdict.OUTSIDE_USER_AREA


class TestSafeDeletion:
    def test_delete_tree_removes_real_tree(self, home: Path) -> None:
        target = home / ".config" / "victim"
        (target / "nested").mkdir(parents=True)
        (target / "nested" / "file.txt").write_text("data")
        policy = PathPolicy(home)
        policy.require_allowed(target)
        identity = FileIdentity.capture(target)
        fd, name = open_parent_nofollow(target)
        try:
            freed, deleted = delete_tree_fd(fd, name, identity)
        finally:
            import os

            os.close(fd)
        assert not target.exists()
        assert freed > 0
        assert str(deleted[0]).endswith("file.txt")

    def test_delete_symlink_not_target(self, home: Path, tmp_path: Path) -> None:
        important = tmp_path / "important"
        important.mkdir()
        (important / "keep.txt").write_text("precious")
        link = home / ".config" / "trick"
        link.symlink_to(important)

        policy = PathPolicy(home)
        policy.require_allowed(link)
        identity = FileIdentity.capture(link)
        assert identity.kind == "symlink"
        fd, name = open_parent_nofollow(link)
        try:
            delete_tree_fd(fd, name, identity)
        finally:
            import os

            os.close(fd)
        assert not link.exists()
        assert (important / "keep.txt").exists(), "symlink target must be untouched"

    def test_identity_change_aborts_delete(self, home: Path) -> None:
        target = home / ".config" / "app"
        target.mkdir()
        identity = FileIdentity.capture(target)
        target.rmdir()
        # Recreating the same path must yield a new inode — but filesystems
        # (ext4 on CI runners) happily recycle the just-freed inode number.
        # Occupy freed numbers with decoys until the recreation is genuinely
        # a new object, so the staleness check is exercised deterministically.
        for i in range(8):
            (home / ".config" / f"decoy-{i}").touch()
            target.mkdir()
            if FileIdentity.capture(target) != identity:
                break
            target.rmdir()
        else:  # pragma: no cover - inode recycling of 8 numbers in a row
            raise AssertionError("could not force a new inode for the same path")
        fd, name = open_parent_nofollow(target)
        try:
            with pytest.raises(FileChanged):
                delete_tree_fd(fd, name, identity)
        finally:
            import os

            os.close(fd)
        assert target.exists(), "recreated object must be left alone"
