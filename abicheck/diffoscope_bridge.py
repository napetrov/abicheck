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

"""Optional diffoscope integration for low-level binary diffs.

Shells out to the ``diffoscope`` command-line tool (not a Python dependency).
If diffoscope is not installed, callers get ``None`` and a logged warning.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

_logger = logging.getLogger("abicheck.diffoscope")

#: Default timeout in seconds for diffoscope execution.
DEFAULT_TIMEOUT: int = 60


def run_diffoscope(
    old_path: Path,
    new_path: Path,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> str | None:
    """Run diffoscope on two files and return the text diff.

    Returns ``None`` if diffoscope is not installed, times out, or fails.
    Never raises — errors are logged and suppressed.
    """
    try:
        result = subprocess.run(
            ["diffoscope", "--text", "-", str(old_path), str(new_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # diffoscope exits 0 for identical, 1 for differences, 2 for errors
        if result.returncode in (0, 1):
            return result.stdout
        _logger.warning("diffoscope exited with code %d: %s", result.returncode, result.stderr[:200])
        return None
    except FileNotFoundError:
        _logger.warning("diffoscope not found on PATH — skipping byte-level diff")
        return None
    except subprocess.TimeoutExpired:
        _logger.warning("diffoscope timed out after %ds — skipping", timeout)
        return None
    except OSError as exc:
        _logger.warning("diffoscope failed: %s", exc)
        return None
