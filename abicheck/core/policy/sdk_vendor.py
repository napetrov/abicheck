"""sdk_vendor policy — Phase 2.

Permissive policy for SDK / vendor libraries: compatible extensions are
encouraged; review-needed changes generate a warning but don't block.
Suitable for: plugin SDKs, optional extensions, vendor-specific APIs.
"""
from __future__ import annotations

from abicheck.core.model import Change, ChangeSeverity, PolicyVerdict

from .base import PolicyProfile


class SdkVendorPolicy(PolicyProfile):
    """Permissive SDK/vendor policy.

    - BREAK → BLOCK (hard breaks always block)
    - REVIEW_NEEDED → WARN (flag for human review, don't block CI)
    - COMPATIBLE_EXTENSION → PASS (extensions explicitly encouraged)
    - SUPPRESSED → PASS
    """

    profile_name = "sdk_vendor"
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
