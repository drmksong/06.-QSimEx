"""Progress events shared by execution and geometry backends."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressUpdate:
    stage: str
    detail: str
    completed: int | None = None
    total: int | None = None
    log: bool = True
