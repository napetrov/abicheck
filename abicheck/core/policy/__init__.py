"""Policy package — Phase 2."""
from __future__ import annotations

from .base import PolicyProfile
from .plugin_abi import PluginAbiPolicy
from .sdk_vendor import SdkVendorPolicy
from .strict_abi import StrictAbiPolicy

PROFILES: dict[str, type[PolicyProfile]] = {
    "strict_abi": StrictAbiPolicy,
    "sdk_vendor": SdkVendorPolicy,
    "plugin_abi": PluginAbiPolicy,
}


def get_profile(name: str) -> PolicyProfile:
    """Instantiate a policy profile by name."""
    cls = PROFILES.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown policy profile {name!r}. "
            f"Available: {sorted(PROFILES)}"
        )
    return cls()


__all__ = [
    "PolicyProfile",
    "StrictAbiPolicy",
    "SdkVendorPolicy",
    "PluginAbiPolicy",
    "PROFILES",
    "get_profile",
]
