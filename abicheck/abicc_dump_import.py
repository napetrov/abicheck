"""Backward-compatibility shim for abicheck.abicc_dump_import.

The module was moved to abicheck.compat.abicc_dump_import in PR #110.
This shim preserves the old import path to avoid breaking downstream consumers.
"""
import warnings

warnings.warn(
    "abicheck.abicc_dump_import is deprecated and will be removed in a future version. "
    "Use abicheck.compat.abicc_dump_import instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .compat.abicc_dump_import import *  # noqa: F401,F403,E402
from .compat.abicc_dump_import import (  # noqa: F401,E402
    import_abicc_perl_dump,
    is_abicc_perl_dump_file,
    looks_like_perl_dump,
)
