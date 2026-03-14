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

"""Detector contracts used by checker orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import AbiSnapshot


class ChangeLike(Protocol):
    kind: object
    symbol: str
    description: str


class Detector(Protocol):
    name: str
    description: str

    def run(self, old: AbiSnapshot, new: AbiSnapshot) -> list[ChangeLike]:
        ...

    def is_supported(self, old: AbiSnapshot, new: AbiSnapshot) -> tuple[bool, str | None]:
        ...


@dataclass(frozen=True)
class DetectorResult:
    name: str
    changes_count: int
    enabled: bool = True
    coverage_gap: str | None = None
