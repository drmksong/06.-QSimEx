"""Backend boundary: existing physics may be adapted, not imported into the core.

Potential reuse: FisherDistribution, PowerLawSampler, DFN intersection geometry,
and RQDCalculator. Legacy Q-prime aggregation and campaign policy are not reused.
"""

from typing import Protocol
from .models import CaseSpec, Signature
from .profiles import JointGeometry, SimulationResult

class JointFactory(Protocol):
    def generate(self, case: CaseSpec, seed: int) -> JointGeometry: ...

class Simulator(Protocol):
    def evaluate(self, signature: Signature, seed: int) -> SimulationResult: ...
