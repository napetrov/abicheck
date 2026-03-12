"""strict_abi policy — Phase 2.

Zero-tolerance ABI policy: any BREAK → BLOCK, any REVIEW_NEEDED → WARN.
Use for: stable system libraries, OS interfaces, toolchain components.
"""
from __future__ import annotations

from abicheck.core.model import Change, ChangeSeverity, PolicyVerdict

from .base import PolicyProfile


class StrictAbiPolicy(PolicyProfile):
    """Zero-tolerance ABI policy.

    - BREAK → BLOCK
    - REVIEW_NEEDED → WARN
    - COMPATIBLE_EXTENSION → PASS (additive changes are always safe)
    - SUPPRESSED → PASS
    """

    profile_name = "strict_abi"
    profile_version = "0.2"

    def classify_change(self, change: Change) -> PolicyVerdict:
        match change.severity:
            case ChangeSeverity.BREAK:
                return PolicyVerdict.BLOCK
            case ChangeSeverity.REVIEW_NEEDED:
                return PolicyVerdict.WARN
            case ChangeSeverity.COMPATIBLE_EXTENSION:
                return PolicyVerdict.PASS
            case _:
                return PolicyVerdict.PASS
