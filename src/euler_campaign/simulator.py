"""Simulation adapter that evaluates one fixed DFN for all case profiles."""

from __future__ import annotations

from hashlib import sha256
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import platform
import sys
from typing import Literal

from .dfn import CaseJointFactory
from .models import GENERATOR_VERSION, Signature, identify_domain
from .ports import JointFactory
from .profiles import (
    PROFILE_CALCULATION_VERSION,
    SimulationResult,
    sample_borehole,
    sample_tunnel,
)
from .qprime import QPRIME_CALCULATION_VERSION

SIMULATOR_VERSION = "qsimex-euler-simulator-v1"
_EXECUTION_SOURCE_FILES = (
    "campaign.py",
    "coverage.py",
    "dfn.py",
    "euler.py",
    "geometry.py",
    "models.py",
    "profiles.py",
    "qprime.py",
    "simulator.py",
)


class EulerSimulator:
    """Generate one whole-domain DFN and evaluate requested profiles."""

    def __init__(self, backend: Literal["numpy", "mlx"] = "numpy") -> None:
        if backend == "numpy":
            self._joint_factory: JointFactory = CaseJointFactory()
            self._generator_version = GENERATOR_VERSION
            self._runtime_info = ("cpu",)
        elif backend == "mlx":
            from .mlx_backend import (
                MLX_GENERATOR_VERSION, MlxCaseJointFactory, require_mlx_gpu,
            )

            self._runtime_info = require_mlx_gpu()
            self._joint_factory = MlxCaseJointFactory()
            self._generator_version = MLX_GENERATOR_VERSION
        else:
            raise ValueError("backend must be 'numpy' or 'mlx'")
        self.backend = backend

    @property
    def runtime_info(self) -> tuple[str, ...]:
        """Return the runtime and device details verified during initialization."""
        return self._runtime_info

    @property
    def execution_fingerprint(self) -> str:
        """Fingerprint the source and runtime that determine simulation evidence."""
        source_root = Path(__file__).parent
        source_files = (*_EXECUTION_SOURCE_FILES,)
        if self.backend == "mlx":
            source_files = (*source_files, "mlx_backend.py")
        source_hash = sha256()
        for name in source_files:
            source_path = source_root / name
            try:
                source_hash.update(name.encode("utf-8"))
                source_hash.update(b"\0")
                source_hash.update(source_path.read_bytes())
                source_hash.update(b"\0")
            except OSError as error:
                raise RuntimeError(
                    f"cannot fingerprint simulator source {source_path}"
                ) from error
        try:
            numpy_version = version("numpy")
            mlx_version = version("mlx") if self.backend == "mlx" else None
        except PackageNotFoundError as error:
            raise RuntimeError("simulation dependency metadata is unavailable") from error
        data = {
            "backend": self.backend,
            "device_runtime": self._runtime_info,
            "generator_version": self._generator_version,
            "numpy_version": numpy_version,
            "mlx_version": mlx_version,
            "profile_version": PROFILE_CALCULATION_VERSION,
            "qprime_version": QPRIME_CALCULATION_VERSION,
            "simulator_version": SIMULATOR_VERSION,
            "source_sha256": source_hash.hexdigest(),
            "python_implementation": platform.python_implementation(),
            "python_version": sys.version,
            "platform": platform.platform(),
        }
        encoded = json.dumps(
            data, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def evaluate(self, signature: Signature, seed: int) -> SimulationResult:
        if not isinstance(signature, Signature):
            raise TypeError("signature must be a Signature")
        domain_id = identify_domain(
            signature, seed, generator_version=self._generator_version,
        )

        joints = self._joint_factory.generate(signature.case, seed)
        boreholes = tuple(
            sample_borehole(signature.case, borehole, joints)
            for borehole in signature.case.boreholes
        )
        tunnel = sample_tunnel(signature.case, signature.case.tunnel, joints)
        return SimulationResult(
            signature_id=signature.signature_id,
            domain_id=domain_id,
            seed=seed,
            boreholes=boreholes,
            tunnel=tunnel,
        )
