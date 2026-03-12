"""plugin_abi policy — Phase 2.

Relaxed policy for plugin/extension interfaces where the plugin contract
is intentionally flexible. REVIEW_NEEDED changes are informational only.
Suitable for: loadable plugins, extension points, optional features.
"""
from __future__ import annotations

from abicheck.core.model import Change, ChangeSeverity, PolicyVerdict

from .base import PolicyProfile


class PluginAbiPolicy(PolicyProfile):
    """Relaxed plugin/extension policy.

    - BREAK → WARN (plugins may be intentionally reloaded at new versions)
    - REVIEW_NEEDED → PASS (informational, not actionable for plugins)
    - COMPATIBLE_EXTENSION → PASS
    - SUPPRESSED → PASS

    Note: If even a WARN is too noisy for your plugin contract,
    consider a suppression rule rather than changing this policy.
    """

    profile_name = "plugin_abi"
    profile_version = "0.2"

    def classify_change(self, change: Change) -> PolicyVerdict:
        match change.severity:
            case ChangeSeverity.BREAK:
                return PolicyVerdict.WARN   # breaking change is a warning for plugins
            case ChangeSeverity.REVIEW_NEEDED:
                return PolicyVerdict.PASS   # informational only
            case ChangeSeverity.COMPATIBLE_EXTENSION:
                return PolicyVerdict.PASS
            case _:
                return PolicyVerdict.PASS
