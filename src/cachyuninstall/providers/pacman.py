"""pacman/libalpm provider — the primary provider.

Wraps AlpmSession into provider-facing immutable Installation objects paired
with identity resolution so the UI can show human names.
"""

from __future__ import annotations

from dataclasses import dataclass

from cachyuninstall.core.alpm_session import AlpmSession
from cachyuninstall.core.identity import Identity, build_identity_index
from cachyuninstall.core.models import PackageName, PackageRecord, ProviderKind
from cachyuninstall.providers.base import Installation


@dataclass(slots=True)
class PacmanProvider:
    session: AlpmSession

    kind: ProviderKind = ProviderKind.PACMAN

    def is_available(self) -> bool:
        try:
            self.session.open()
            return True
        except Exception:
            return False

    def packages(self) -> list[PackageRecord]:
        return self.session.packages()

    def identities(self, packages: list[PackageRecord]) -> dict[PackageName, Identity]:
        return build_identity_index(packages)

    def list_installations(
        self,
        packages: list[PackageRecord] | None = None,
        identities: dict[PackageName, Identity] | None = None,
    ) -> list[Installation]:
        """Rows for the application list. Accepts pre-enumerated records and
        identities so the startup path enumerates the local db once (§83/§145)."""
        packages = packages if packages is not None else self.session.packages()
        identities = identities if identities is not None else build_identity_index(packages)
        return [self._to_row(pkg, identities.get(pkg.name)) for pkg in packages]

    def list_installations_light(self, packages: list[PackageRecord]) -> list[Installation]:
        """Fast first paint: package name as display, no icon/desktop parsing."""
        return [self._to_row(pkg, None) for pkg in packages]

    @staticmethod
    def _to_row(pkg: PackageRecord, ident: Identity | None) -> Installation:
        return Installation(
            instance_id=f"pacman:{pkg.name}",
            provider=ProviderKind.PACMAN,
            name=str(pkg.name),
            display_name=ident.display_name if ident else str(pkg.name),
            version=pkg.version,
            origin=pkg.origin,
            size_bytes=pkg.size_bytes,
            summary=pkg.description,
            icon_name=ident.icon_names[0] if ident and ident.icon_names else "",
            install_date=pkg.install_date,
        )
