"""Leftover scanner — the evidence-based leftover analyzer (§49-§64).

Pipeline:
    identity -> targeted discovery (rules) -> evidence -> ownership veto ->
    sharing checks -> confidence -> candidates for human review.

The scanner NEVER deletes; it returns immutable candidates. Every candidate
carries: rule id, evidence reason, category, confidence, ownership.

False negatives are by design preferable to false positives (§3).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from cachyuninstall.core.identity import Identity
from cachyuninstall.core.models import (
    Confidence,
    LeftoverCandidate,
    LeftoverCategory,
    PackageName,
)
from cachyuninstall.core.ownership import OwnershipOracle
from cachyuninstall.core.paths import PathPolicy, PathVerdict


@dataclass(frozen=True, slots=True)
class ScanContext:
    """Everything the rules are allowed to know."""

    home: Path
    identity: Identity  # the application being analyzed
    other_identities: tuple[Identity, ...]  # all *other* installed identities
    oracle: OwnershipOracle


class LeftoverRule:
    """Base class for discovery rules. Subclasses set RULE_ID + doc the why."""

    RULE_ID: str = "RULE-BASE"
    CATEGORY: LeftoverCategory = LeftoverCategory.APPLICATION_DATA

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        raise NotImplementedError


# ------------------------------------------------------------ XDG token rules


def _exact_token_dirs(base: Path, tokens: frozenset[str]) -> Iterable[Path]:
    """Yield base/<dir> entries whose lowercase name is exactly one token."""
    try:
        with os.scandir(base) as it:
            for entry in it:
                if entry.name.lower() in tokens:
                    yield base / entry.name
    except OSError:
        return


class RuleXdgConfig(LeftoverRule):
    """Exact identity token directory under ~/.config. RULE-XDG-CONFIG."""

    RULE_ID = "RULE-XDG-CONFIG"
    CATEGORY = LeftoverCategory.CONFIGURATION

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        yield from _exact_token_dirs(ctx.home / ".config", ctx.identity.candidate_names)


class RuleXdgCache(LeftoverRule):
    """Exact identity token directory under ~/.cache. RULE-XDG-CACHE."""

    RULE_ID = "RULE-XDG-CACHE"
    CATEGORY = LeftoverCategory.CACHE

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        yield from _exact_token_dirs(ctx.home / ".cache", ctx.identity.candidate_names)


class RuleXdgData(LeftoverRule):
    """Exact identity token directory under ~/.local/share. RULE-XDG-DATA."""

    RULE_ID = "RULE-XDG-DATA"
    CATEGORY = LeftoverCategory.APPLICATION_DATA

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        yield from _exact_token_dirs(ctx.home / ".local/share", ctx.identity.candidate_names)


class RuleXdgState(LeftoverRule):
    """Exact identity token directory under ~/.local/state. RULE-XDG-STATE."""

    RULE_ID = "RULE-XDG-STATE"
    CATEGORY = LeftoverCategory.STATE

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        yield from _exact_token_dirs(ctx.home / ".local/state", ctx.identity.candidate_names)


class RuleAutostart(LeftoverRule):
    """Autostart desktop file named after a desktop id. RULE-AUTOSTART."""

    RULE_ID = "RULE-AUTOSTART"
    CATEGORY = LeftoverCategory.DESKTOP_INTEGRATION

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        d = ctx.home / ".config" / "autostart"
        for did in ctx.identity.desktop_ids:
            candidate = d / f"{did}.desktop"
            if candidate.exists():
                yield candidate


class RuleUserDesktopFile(LeftoverRule):
    """User-level .desktop launchers matching the identity. RULE-USER-DESKTOP."""

    RULE_ID = "RULE-USER-DESKTOP"
    CATEGORY = LeftoverCategory.DESKTOP_INTEGRATION

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        d = ctx.home / ".local" / "share" / "applications"
        for did in ctx.identity.desktop_ids:
            candidate = d / f"{did}.desktop"
            if candidate.exists():
                yield candidate


class RuleSystemdUserUnit(LeftoverRule):
    """User units whose unit name equals a desktop id. RULE-SYSTEMD-USER."""

    RULE_ID = "RULE-SYSTEMD-USER"
    CATEGORY = LeftoverCategory.SYSTEMD_USER_UNIT

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        d = ctx.home / ".config" / "systemd" / "user"
        for did in ctx.identity.desktop_ids:
            for suffix in (".service", ".timer", ".socket", ".path"):
                for candidate in (d / f"{did}{suffix}", d / f"{did}.service.d"):
                    if candidate.exists():
                        yield candidate


# ------------------------------------------------------ Application data rules
# Evidence-backed known application data locations (§7-§19 of release hardening)


@dataclass(frozen=True, slots=True)
class AppDataRule:
    """Evidence-backed rule for known application data locations.

    Unlike token-based rules, these describe specific known locations where
    an application stores data that don't follow the simple token-matching
    pattern. Each rule must provide evidence and verification.
    """

    rule_id: str
    """Unique identifier, e.g. 'RULE-APPDATA-FIREFOX-PROFILE'."""

    application_ids: tuple[str, ...]
    """Package names or desktop IDs this rule applies to (case-insensitive)."""

    category: LeftoverCategory
    """Category for the candidate."""

    base_paths: tuple[Path, ...]
    """Base directories to search under (relative to home)."""

    path_pattern: Callable[[Path], Iterable[Path]]
    """Given a base directory, yield candidate paths to check."""

    evidence: str
    """Human-readable explanation of why this location belongs to the application."""

    verification: Callable[[Path], tuple[bool, str]] | None = None
    """Optional verification function. Returns (matches, detail).
    If provided, the candidate must pass verification to be considered a match."""

    base_confidence: Confidence = Confidence.MEDIUM
    """Confidence when base path exists but verification not run or inconclusive."""

    verified_confidence: Confidence = Confidence.HIGH
    """Confidence when verification passes."""

    def applies_to(self, identity: Identity) -> bool:
        """Check if this rule applies to the given identity."""
        id_tokens = {identity.package.lower()}
        id_tokens.update(did.lower() for did in identity.desktop_ids)
        id_tokens.update(exe.lower() for exe in identity.executables)
        return any(app_id.lower() in id_tokens for app_id in self.application_ids)

    def discover(self, ctx: ScanContext) -> Iterable[Path]:
        """Yield candidate paths that match this rule."""
        if not self.applies_to(ctx.identity):
            return
        for base in self.base_paths:
            full_base = ctx.home / base
            if not full_base.exists():
                continue
            for candidate in self.path_pattern(full_base):
                if candidate.exists():
                    yield candidate


# ------------------------------------------------------ Firefox rule
# First regression case: Firefox stores data in ~/.mozilla/firefox


def _firefox_profile_pattern(base: Path) -> Iterable[Path]:
    """Yield Firefox profile directories under ~/.mozilla/firefox/."""
    firefox_dir = base / "firefox"
    if not firefox_dir.exists():
        return
    try:
        with os.scandir(firefox_dir) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    # Only yield directories that look like Firefox profiles
                    # (contain profile metadata like profiles.ini or cert9.db)
                    yield firefox_dir / entry.name
    except OSError:
        return


def _verify_firefox_profile(path: Path) -> tuple[bool, str]:
    """Verify a directory is a Firefox profile by checking for profile markers."""
    # Firefox profiles contain specific files
    markers = (
        "prefs.js",
        "cert9.db",
        "key4.db",
        "places.sqlite",
        "profiles.ini",
    )
    for marker in markers:
        if (path / marker).exists():
            return True, f"Firefox profile marker found: {marker}"
    # Check for profiles.ini in parent (firefox directory)
    parent_ini = path.parent / "profiles.ini"
    if parent_ini.exists():
        try:
            content = parent_ini.read_text(encoding="utf-8", errors="replace")
            if path.name in content:
                return True, "Profile listed in profiles.ini"
        except OSError:
            pass
    return False, "No Firefox profile markers found"


# Known application data rules registry
# Each rule is documented with evidence and must have tests
APP_DATA_RULES: tuple[AppDataRule, ...] = (
    AppDataRule(
        rule_id="RULE-APPDATA-FIREFOX-PROFILE",
        application_ids=("firefox", "org.mozilla.firefox", "mozilla-firefox"),
        category=LeftoverCategory.APPLICATION_DATA,
        base_paths=(Path(".mozilla"),),
        path_pattern=_firefox_profile_pattern,
        evidence=(
            "Firefox stores profile data (bookmarks, history, passwords, "
            "preferences) in ~/.mozilla/firefox/<profile>/. This is the "
            "documented Linux profile location per Mozilla documentation."
        ),
        verification=_verify_firefox_profile,
        base_confidence=Confidence.MEDIUM,
        verified_confidence=Confidence.HIGH,
    ),
)


ALL_RULES: tuple[type[LeftoverRule], ...] = (
    RuleXdgConfig,
    RuleXdgCache,
    RuleXdgData,
    RuleXdgState,
    RuleAutostart,
    RuleUserDesktopFile,
    RuleSystemdUserUnit,
)


# ------------------------------------------------------------------- scanner

_REASON_TEMPLATES: dict[str, str] = {
    "RULE-XDG-CONFIG": "Configuration directory named exactly after the application.",
    "RULE-XDG-CACHE": "Cache directory named exactly after the application.",
    "RULE-XDG-DATA": "Data directory named exactly after the application.",
    "RULE-XDG-STATE": "State directory named exactly after the application.",
    "RULE-AUTOSTART": "Autostart entry whose name matches the application's desktop id.",
    "RULE-USER-DESKTOP": "User-level launcher whose name matches the application's desktop id.",
    "RULE-SYSTEMD-USER": "User systemd unit named after the application's desktop id.",
}


def _measure(path: Path) -> int:
    """Bytes on disk (st_blocks); broken/dangling trees count as zero-safe."""
    total = 0
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    total += getattr(st, "st_blocks", 0) * 512
    if os.path.isdir(path) and not os.path.islink(path):
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            est = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        total += est.st_blocks * 512
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
            except OSError:
                continue
    return total


class LeftoverScanner:
    """Orchestrates rules and assigns confidence. Read-only."""

    def __init__(
        self,
        policy: PathPolicy,
        rules: Iterable[LeftoverRule] | None = None,
        app_data_rules: Iterable[AppDataRule] | None = None,
    ) -> None:
        self._policy = policy
        self._rules: tuple[LeftoverRule, ...] = (
            tuple(rules) if rules is not None else tuple(rule() for rule in ALL_RULES)
        )
        self._app_data_rules: tuple[AppDataRule, ...] = (
            tuple(app_data_rules) if app_data_rules is not None else APP_DATA_RULES
        )

    def scan(self, ctx: ScanContext, *, measure: bool = True) -> list[LeftoverCandidate]:
        others_tokens: dict[str, list[PackageName]] = {}
        for other in ctx.other_identities:
            for token in other.candidate_names:
                others_tokens.setdefault(token, []).append(other.package)

        seen: set[Path] = set()
        out: list[LeftoverCandidate] = []

        # Run standard token-based rules
        for rule in self._rules:
            for path in rule.discover(ctx):
                if path in seen:
                    continue
                seen.add(path)
                out.extend(self._evaluate_candidate(ctx, rule, path, measure))

        # Run evidence-backed application data rules
        for app_rule in self._app_data_rules:
            for path in app_rule.discover(ctx):
                if path in seen:
                    continue
                seen.add(path)
                out.extend(self._evaluate_app_data_candidate(ctx, app_rule, path, measure))

        out.sort(key=lambda c: (c.confidence.value, str(c.path)))
        return out

    def _evaluate_candidate(
        self, ctx: ScanContext, rule: LeftoverRule, path: Path, measure: bool
    ) -> list[LeftoverCandidate]:
        verdict = self._policy.classify(path)
        if verdict is not PathVerdict.ALLOWED_USER:
            return [
                LeftoverCandidate(
                    path=path,
                    category=rule.CATEGORY,
                    confidence=Confidence.PROTECTED,
                    rule_id=rule.RULE_ID,
                    reason=f"Protected: {verdict.value}.",
                    size_bytes=0,
                    owner_package=None,
                )
            ]

        owners = ctx.oracle.package_claims_below(str(path)) or ctx.oracle.package_owners(str(path))
        owners = tuple(o for o in owners if o != ctx.identity.package)
        token = path.stem if not path.is_dir() else path.name

        # Build others_tokens for sharing check
        others_tokens: dict[str, list[PackageName]] = {}
        for other in ctx.other_identities:
            for t in other.candidate_names:
                others_tokens.setdefault(t, []).append(other.package)

        shared = [pkg for pkg_tok, pkgs in others_tokens.items() if pkg_tok == token.lower() for pkg in pkgs]
        if owners:
            return [
                LeftoverCandidate(
                    path=path,
                    category=rule.CATEGORY,
                    confidence=Confidence.PROTECTED,
                    rule_id=rule.RULE_ID,
                    reason=f"Protected: owned by installed package(s): {', '.join(owners)}.",
                    size_bytes=_measure(path) if measure else 0,
                    owner_package=owners[0],
                )
            ]
        elif shared:
            return [
                LeftoverCandidate(
                    path=path,
                    category=rule.CATEGORY,
                    confidence=Confidence.PROTECTED,
                    rule_id=rule.RULE_ID,
                    reason=f"Protected: also referenced by {', '.join(sorted(set(shared)))}.",
                    size_bytes=_measure(path) if measure else 0,
                    owner_package=None,
                    shared_with=tuple(sorted(set(shared))),
                )
            ]
        else:
            confidence = (
                Confidence.HIGH
                if rule.RULE_ID in {"RULE-AUTOSTART", "RULE-USER-DESKTOP", "RULE-SYSTEMD-USER"}
                else Confidence.MEDIUM
            )
            if token.lower() == str(ctx.identity.package).lower():
                confidence = Confidence.HIGH
            return [
                LeftoverCandidate(
                    path=path,
                    category=rule.CATEGORY,
                    confidence=confidence,
                    rule_id=rule.RULE_ID,
                    reason=_REASON_TEMPLATES.get(rule.RULE_ID, "Matched application identity."),
                    size_bytes=_measure(path) if measure else 0,
                    owner_package=None,
                )
            ]

    def _evaluate_app_data_candidate(
        self, ctx: ScanContext, rule: AppDataRule, path: Path, measure: bool
    ) -> list[LeftoverCandidate]:
        verdict = self._policy.classify(path)
        if verdict is not PathVerdict.ALLOWED_USER:
            return [
                LeftoverCandidate(
                    path=path,
                    category=rule.category,
                    confidence=Confidence.PROTECTED,
                    rule_id=rule.rule_id,
                    reason=f"Protected: {verdict.value}.",
                    size_bytes=0,
                    owner_package=None,
                )
            ]

        owners = ctx.oracle.package_claims_below(str(path)) or ctx.oracle.package_owners(str(path))
        owners = tuple(o for o in owners if o != ctx.identity.package)
        if owners:
            return [
                LeftoverCandidate(
                    path=path,
                    category=rule.category,
                    confidence=Confidence.PROTECTED,
                    rule_id=rule.rule_id,
                    reason=f"Protected: owned by installed package(s): {', '.join(owners)}.",
                    size_bytes=_measure(path) if measure else 0,
                    owner_package=owners[0],
                )
            ]

        # Check for sharing with other identities
        # Use identity's candidate names for sharing check, not path stem
        others_tokens: dict[str, list[PackageName]] = {}
        for other in ctx.other_identities:
            for t in other.candidate_names:
                others_tokens.setdefault(t, []).append(other.package)
        # Check if any of our identity's tokens are shared
        shared_list: list[PackageName] = []
        for our_token in ctx.identity.candidate_names:
            if our_token in others_tokens:
                shared_list.extend(others_tokens[our_token])
        shared = tuple(set(shared_list))
        if shared:
            return [
                LeftoverCandidate(
                    path=path,
                    category=rule.category,
                    confidence=Confidence.PROTECTED,
                    rule_id=rule.rule_id,
                    reason=f"Protected: also referenced by {', '.join(sorted(set(shared)))}.",
                    size_bytes=_measure(path) if measure else 0,
                    owner_package=None,
                    shared_with=tuple(sorted(set(shared))),
                )
            ]

        # Run verification if provided
        verified = False
        verify_detail = ""
        if rule.verification:
            verified, verify_detail = rule.verification(path)

        confidence = rule.verified_confidence if verified else rule.base_confidence
        reason = rule.evidence
        if verified and verify_detail:
            reason = f"{reason} Verification: {verify_detail}."

        return [
            LeftoverCandidate(
                path=path,
                category=rule.category,
                confidence=confidence,
                rule_id=rule.rule_id,
                reason=reason,
                size_bytes=_measure(path) if measure else 0,
                owner_package=None,
            )
        ]
