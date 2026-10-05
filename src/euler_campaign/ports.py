"""Structural protocols for injected campaign simulation backends."""

from __future__ import annotations

from typing import Protocol

from .models import CaseSpec, Signature
from .profiles import JointGeometry, SimulationResult


class JointFactory(Protocol):
    def generate(self, case: CaseSpec, seed: int) -> JointGeometry: ...


class Simulator(Protocol):
    def evaluate(self, signature: Signature, seed: int) -> SimulationResult: ...
