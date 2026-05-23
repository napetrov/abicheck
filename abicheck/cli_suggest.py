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

"""CLI — ``suggest-suppressions`` command.

Split out of :mod:`abicheck.cli` to keep that module under the
AI-readiness file-size limit. Imported for side-effect at the bottom of
:mod:`abicheck.cli` so the ``@main.command("suggest-suppressions")``
decorator runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from .cli import _write_or_echo, main


@main.command("suggest-suppressions")
@click.argument("diff_json", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None,
              help="Output file for candidate suppressions (default: stdout).")
@click.option("--expiry-days", type=click.IntRange(min=0), default=180, show_default=True,
              help="Number of days from today for the expires field.")
def suggest_suppressions_cmd(
    diff_json: Path,
    output: Path | None,
    expiry_days: int,
) -> None:
    """Generate candidate suppression rules from a JSON diff result.

    DIFF_JSON is a JSON file produced by 'abicheck compare --format json'.

    \b
    Example:
      abicheck compare old.so new.so -H include/ --format json -o diff.json
      abicheck suggest-suppressions diff.json -o candidates.yml
    """

    from .suppression import suggest_suppressions

    try:
        text = diff_json.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as e:
        raise click.ClickException(f"Cannot read JSON diff: {e}") from e

    if not isinstance(data, dict):
        raise click.ClickException(
            "JSON diff must be an object with a 'changes' key"
        )
    if "changes" not in data:
        raise click.ClickException(
            "JSON diff is missing required 'changes' key"
        )
    changes = data["changes"]
    if not isinstance(changes, list):
        raise click.ClickException("'changes' must be an array")
    for i, entry in enumerate(changes):
        if not isinstance(entry, dict):
            raise click.ClickException(
                f"changes[{i}] must be an object, got {type(entry).__name__}"
            )

    yaml_text = suggest_suppressions(changes, expiry_days=expiry_days)
    _write_or_echo(output, yaml_text)
