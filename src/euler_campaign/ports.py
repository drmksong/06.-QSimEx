"""Structural protocols for injected campaign simulation backends."""

from __future__ import annotations

from typing import Callable, Protocol

from .models import CaseSpec, Signature
from .profiles import JointGeometry, SimulationResult
from .progress import ProgressUpdate


class JointFactory(Protocol):
    def generate(
        self,
        case: CaseSpec,
        seed: int,
        *,
        progress_callback: Callable[[ProgressUpdate], None] | None = None,
    ) -> JointGeometry: ...


class Simulator(Protocol):
    def evaluate(self, signature: Signature, seed: int) -> SimulationResult: ...
