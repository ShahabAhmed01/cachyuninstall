"""TEMPORARY physical acceptance tests: leftover safety + quarantine (§280-282, §287).

Runs REAL filesystem operations as root inside the disposable container.
Each check prints PASS/FAIL and the process exit code is the count of failures.
"""

from __future__ import annotations

import os
from pathlib import Path

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    from cachyuninstall.core.filesystem import CleanupExecutor, Quarantine
    from cachyuninstall.core.identity import Identity, parse_desktop_file
    from cachyuninstall.core.leftovers import LeftoverScanner, ScanContext
    from cachyuninstall.core.models import Confidence, LeftoverCandidate, LeftoverCategory, PackageName
    from cachyuninstall.core.ownership import DictOwnerIndex, OwnershipOracle
    from cachyuninstall.core.paths import PathPolicy, delete_tree_fd, open_parent_nofollow

    home = Path(os.environ.get("HOME", "/root")).resolve()
    policy = PathPolicy(home)
    other = PackageName("vim")  # another installed app used for sharing tests

    # ---------------------------------------------------- E: shared user data
    # §280: a directory whose token matches the TARGET app must still be
    # PROTECTED when another *installed* app also claims that token.
    # Target = package "vim"; another installed app (desktop id "vim.editor",
    # tail token "vim") also claims the token.
    shared_dir = home / ".config" / "vim"
    shared_dir.mkdir(parents=True, exist_ok=True)
    (shared_dir / "vimrc.local").write_text("set nocompatible\n")
    oracle = OwnershipOracle(DictOwnerIndex({}))
    ctx = ScanContext(
        home=home,
        identity=Identity(package=PackageName("vim")),  # scanning vim...
        other_identities=(  # ...but another installed app claims "vim" too
            Identity(package=PackageName("othervim"), desktop_ids=("vim",)),
        ),
        oracle=oracle,
    )
    cands = LeftoverScanner(policy).scan(ctx)
    shared = [c for c in cands if c.path == shared_dir]
    check(
        "E shared-user-data PROTECTED (token also claimed by installed app)",
        bool(shared) and shared[0].confidence is Confidence.PROTECTED,
        detail=str(shared[0].reason) if shared else "candidate not found",
    )

    # ---------------------------------------------------------- F: symlink
    # ~/.config/evilapp -> ~/important ; cleaning must remove link only.
    important = home / "important_data"
    important.mkdir(exist_ok=True)
    (important / "keep.txt").write_text("DO NOT DELETE\n")
    link = home / ".config" / "evilapp"
    if link.is_symlink() or link.exists():
        os.unlink(link)
    link.symlink_to(important)
    ident_ctx = ScanContext(
        home=home,
        identity=Identity(package=PackageName("evilapp")),
        other_identities=(),
        oracle=oracle,
    )
    link_cands = [c for c in LeftoverScanner(policy).scan(ident_ctx) if c.path == link]
    check("F symlink discovered as candidate", bool(link_cands))
    if link_cands:
        report = CleanupExecutor(policy, quarantine=None).execute(link_cands)
        link_gone = not os.path.lexists(link)
        target_ok = (important / "keep.txt").exists() and (
            important / "keep.txt"
        ).read_text() == "DO NOT DELETE\n"
        check("F symlink removed", link_gone)
        check("F symlink TARGET untouched", target_ok)
        check("F report ok", all(i.ok for i in report.items), detail=str(report.items))

    # Direct primitive check too (delete_tree_fd on a symlink unlink, no follow).
    if not link.exists() and not link.is_symlink():
        link.symlink_to(important)
        from cachyuninstall.core.paths import FileIdentity

        ident = FileIdentity.capture(link)
        pfd, name = open_parent_nofollow(link)
        try:
            delete_tree_fd(pfd, name, ident)
        finally:
            os.close(pfd)
        check(
            "F primitive delete_tree_fd removes link only",
            not os.path.lexists(link) and (important / "keep.txt").exists(),
        )

    # ------------------------------------------------------- G: ownership
    # DictOwnerIndex keys are db-relative WITHOUT leading '/' (see its doc:
    # e.g. "usr/bin/foo") — mirror that contract here.
    owned_dir = home / ".config" / "ownedapp"
    owned_dir.mkdir(parents=True, exist_ok=True)
    (owned_dir / "data").write_text("x")
    owned_key = str(owned_dir).lstrip("/")  # "root/.config/ownedapp"
    owned_oracle = OwnershipOracle(
        DictOwnerIndex({owned_key: ("somepkg",), owned_key + "/data": ("somepkg",)})
    )
    owned_ctx = ScanContext(
        home=home,
        identity=Identity(package=PackageName("ownedapp")),
        other_identities=(),
        oracle=owned_oracle,
    )
    owned_cands = [c for c in LeftoverScanner(policy).scan(owned_ctx) if c.path == owned_dir]
    check(
        "G ownership PROTECTED with owner named",
        bool(owned_cands)
        and owned_cands[0].confidence is Confidence.PROTECTED
        and "somepkg" in owned_cands[0].reason,
        detail=str(owned_cands[0].reason) if owned_cands else "not found",
    )
    # And the executor must refuse to touch it.
    if owned_cands:
        rep = CleanupExecutor(policy, quarantine=None).execute(owned_cands)
        check(
            "G executor refuses owned path",
            owned_dir.exists() and all(not i.ok for i in rep.items),
        )

    # ------------------------------------------------- L: .desktop Exec abuse
    evil_desktop = home / ".config" / "evil.desktop"
    evil_desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Evil\n"
        "Exec=bash -c 'touch /tmp/cachyuninstall-pwned; rm -rf /'\n"
    )
    marker = Path("/tmp/cachyuninstall-pwned")
    if marker.exists():
        marker.unlink()
    entry = parse_desktop_file(evil_desktop)
    check("L desktop file parsed as DATA", entry is not None)
    check("L Exec captured but NOT executed", not marker.exists())
    if entry is not None:
        check("L exec_line preserved verbatim", "touch /tmp/cachyuninstall-pwned" in entry.exec_line)
        check("L exec_binary_guess does not run anything", not marker.exists(), detail=entry.exec_binary_guess)

    # ---------------------------------------------------- quarantine physical
    # Use a fresh base per run: manifests accumulate per txn, and a rerun must
    # not see yesterday's entries (that made restore hit its overwrite guard).
    import shutil

    qbase = home / ".local" / "share" / "cachyuninstall" / "quarantine-test-tmp"
    shutil.rmtree(qbase, ignore_errors=True)
    victim_dir = home / ".config" / "quarvictim"
    if os.path.lexists(victim_dir):
        if victim_dir.is_dir() and not victim_dir.is_symlink():
            shutil.rmtree(victim_dir)
        else:
            os.unlink(victim_dir)
    victim_dir.mkdir(parents=True, exist_ok=True)
    (victim_dir / "settings.ini").write_text("remembered=true\n")
    from cachyuninstall.core.paths import FileIdentity

    quarantine = Quarantine(base=qbase)
    ident = FileIdentity.capture(victim_dir)
    dest = quarantine.store("txn-test", ident, 4096)
    check("Q item moved into quarantine", dest.exists() and not os.path.lexists(victim_dir))
    entries = quarantine.list_entries()
    check("Q manifest written", any(e.original_path == str(victim_dir) for e in entries))
    restored_ok = False
    for e in entries:
        if e.original_path == str(victim_dir):
            quarantine.restore(e, policy)
            restored_ok = (victim_dir / "settings.ini").exists() and (
                victim_dir / "settings.ini"
            ).read_text() == "remembered=true\n"
    check("Q restore brings original back with content", restored_ok)
    # restore must refuse to overwrite an existing target
    if restored_ok:
        from cachyuninstall.core.errors import CuError

        try:
            for e in entries:
                if e.original_path == str(victim_dir):
                    quarantine.restore(e, policy)
            check("Q restore refuses overwrite", False)
        except CuError:
            check("Q restore refuses overwrite", True)

    # ---------------------------------------------------- policy sanity (N)
    check("P /etc rejected", policy.classify(Path("/etc/passwd")).value == "protected_system")
    check("P /usr rejected", policy.classify(Path("/usr/bin/foo")).value == "protected_system")
    check("P relative rejected", policy.classify(Path(".config/x")).value == "protected_system")
    check(
        "P own quarantine state protected",
        policy.classify(home / ".config" / "cachyuninstall").value == "protected_name",
    )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES: {FAILURES}")
        return 1
    print("ALL PHYSICAL FS SAFETY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
