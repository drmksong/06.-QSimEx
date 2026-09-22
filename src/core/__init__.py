"""
Q-Rock Simulator Core Engine
=============================
터널 Q-System 공간분석 시뮬레이터 핵심 모듈
"""

from .joint_models import (
    JointSetDefinition,
    DomainJointConfig,
    Joint,
    FisherDistribution,
    PowerLawSampler,
)
from .dfn_generator import DiscreteFractureNetwork
from .rqd_calculator import RQDCalculator, DirectionalRQDCalculator
from .grid_assigner import GridParameterAssigner
from .domain import RockDomain, AnalysisCase
from .tunnel_old import Tunnel
from .q_calculator import QCalculator
from .comparison import ComparisonEngine
from .case_library import CaseLibrary

__version__ = '0.2.0'