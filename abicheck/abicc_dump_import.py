# Copyright 2026 Nikolay Petrov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
