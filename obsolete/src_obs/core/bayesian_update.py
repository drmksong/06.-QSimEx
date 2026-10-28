"""
Bayesian update module for rock mass suitability analysis.

이 모듈은 시추공 관측 결과를 바탕으로 암반 적합성(Suitability)의 사후 확률을 계산합니다.
현재는 이진(Binary) 분류를 지원하며, 향후 암반 등급별(Multi-class) 확장이 가능하도록 설계되었습니다.

핵심 원칙:
1. DFN 시뮬레이션: Likelihood (Sensitivity, Specificity) 제공.
2. 현장(Field): Prior, Costs, Observation 제공.
"""

import numpy as np
from typing import Union, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class LikelihoodConfig:
    """
    DFN 시뮬레이션의 Confusion Matrix로부터 도출된 가능도(Likelihood) 파라미터.

    보고서 문안: "DFN 기반 시뮬레이션을 통해 산정된 borehole Q' 판정과 reference 암반상태 사이의
    민감도(Sensitivity)와 특이도(Specificity)를 Bayesian likelihood로 사용함."
    """

    sensitivity: float  # P(B=1 | Z=1): 실제 적합할 때 시추공이 적합하다고 할 확률
    specificity: float  # P(B=0 | Z=0): 실제 부적합할 때 시추공이 부적합하다고 할 확률

    @property
    def false_positive_rate(self) -> float:
        return 1.0 - self.specificity  # P(B=1 | Z=0)

    @property
    def false_negative_rate(self) -> float:
        return 1.0 - self.sensitivity  # P(B=0 | Z=1)


@dataclass
class SiteContext:
    """
    실제 시공 현장에서 관리 및 입력해야 하는 컨텍스트 정보.

    Example Usage
    -------------
    >>> # 1. 시뮬레이션에서 얻은 장비 신뢰도 (Likelihood)
    >>> likelihood = LikelihoodConfig(sensitivity=0.85, specificity=0.75)
    >>>
    >>> # 2. 처분장 건설 정책에 따른 비용 구조 (FN 비용이 훨씬 높음)
    >>> costs = DecisionCost(cost_fp=10.0, cost_fn=50.0)
    >>>
    >>> # 3. 현장 컨텍스트 설정 (사전 확률 70%, 기준 Q' 4.0)
    >>> context = SiteContext(
    ...     prior_suitable=0.7,
    ...     likelihood=likelihood,
    ...     costs=costs,
    ...     borehole_threshold=4.0
    ... )
    >>>
    >>> # 4. 현장에서 시추공 Q' = 3.5 측정 시 의사결정 수행
    >>> result = context.update_with_observation(3.5)
    >>> print(result['decision'])  # 'excavate' 또는 'skip' 반환
    """

    prior_suitable: float  # 현장 지질 통계 기반 사전 확률 P(Z=1)
    likelihood: LikelihoodConfig  # 시뮬레이션에서 얻은 장비/평가법의 신뢰도
    costs: "DecisionCost"  # 프로젝트 정책에 따른 비대칭 손실 비용
    borehole_threshold: float  # 시추공 Q'의 적합/부적합 판단 기준점 (예: 4.0)

    def update_with_observation(self, observed_q_prime: float) -> Dict[str, Any]:
        """현장 관측값을 입력받아 최종 의사결정을 수행함"""
        obs_class = 1 if observed_q_prime >= self.borehole_threshold else 0
        posterior = bayesian_update_binary(
            self.prior_suitable,
            obs_class,
            self.likelihood.sensitivity,
            self.likelihood.specificity,
        )
        return bayesian_decision_from_posterior(posterior, self.costs)


@dataclass
class DecisionCost:
    """
    의사결정 손실 비용 구조 정의.

    Attributes
    ----------
    cost_fp : float
        부적합한 암반을 굴착했을 때 발생하는 손실 (건설비 낭비, 복구 비용 등).
    cost_fn : float
    적합한 암반 부지를 포기했을 때 발생하는 기회 비용 (부지 자원 손실).
    방사성 폐기물 처분장처럼 부지 확보가 어려운 경우 이 값이 `cost_fp`보다 훨씬 커질 수 있음.
    """

    cost_fp: float = 1.0
    cost_fn: float = 5.0

    def __post_init__(self):
        try:
            self.cost_fp = float(self.cost_fp)
            self.cost_fn = float(self.cost_fn)
        except (TypeError, ValueError):
            self.cost_fp = 1.0
            self.cost_fn = 5.0

        if not np.isfinite(self.cost_fp) or self.cost_fp < 0:
            self.cost_fp = 1.0
        if not np.isfinite(self.cost_fn) or self.cost_fn < 0:
            self.cost_fn = 5.0

    @property
    def p_threshold(self) -> float:
        """경제성 관점의 사후 확률 임계치: P(suitable) > p_threshold 이면 굴착 선택"""
        total = self.cost_fp + self.cost_fn
        return self.cost_fp / total if total > 0 else 0.5


def bayesian_update_binary(
    prior_suitable: float,
    observed_borehole_class: int,
    sensitivity: float,
    specificity: float,
) -> float:
    """
    시추공 관측 등급을 이용한 이진 암반 적합성 베이지안 업데이트.
    """
    try:
        p = float(prior_suitable)
        sens = float(sensitivity)
        spec = float(specificity)
    except (TypeError, ValueError):
        return np.nan

    if not np.isfinite(p) or not 0.0 <= p <= 1.0:
        return np.nan
    if not np.isfinite(sens) or not 0.0 <= sens <= 1.0:
        return np.nan
    if not np.isfinite(spec) or not 0.0 <= spec <= 1.0:
        return np.nan

    if observed_borehole_class == 1:
        likelihood_suitable = sens
        likelihood_unsuitable = 1.0 - spec
    elif observed_borehole_class == 0:
        likelihood_suitable = 1.0 - sens
        likelihood_unsuitable = spec
    else:
        return np.nan

    numerator = likelihood_suitable * p
    denominator = numerator + likelihood_unsuitable * (1.0 - p)

    return float(numerator / denominator) if denominator > 0 else np.nan


def bayesian_decision_from_posterior(
    posterior_suitable: float, cost_config: Optional[DecisionCost] = None
) -> Dict[str, Any]:
    """
    사후 확률(Posterior)과 비대칭 손실 비용(Asymmetric Costs)을 바탕으로 굴착 여부를 결정합니다.
    """
    if cost_config is None:
        cost_config = DecisionCost()

    try:
        p = float(posterior_suitable)
    except (TypeError, ValueError):
        p = np.nan

    if not np.isfinite(p) or not 0.0 <= p <= 1.0:
        p = np.nan
        expected_loss_excavate = np.nan
        expected_loss_skip = np.nan
        decision = "skip"
    else:
        c_fp = cost_config.cost_fp
        c_fn = cost_config.cost_fn
        expected_loss_excavate = c_fp * (1.0 - p)
        expected_loss_skip = c_fn * p
        decision = "excavate" if expected_loss_excavate < expected_loss_skip else "skip"

    return {
        "posterior_suitable": float(p) if np.isfinite(p) else np.nan,
        "p_threshold": float(cost_config.p_threshold),
        "expected_loss_excavate": float(expected_loss_excavate) if np.isfinite(expected_loss_excavate) else np.nan,
        "expected_loss_skip": float(expected_loss_skip) if np.isfinite(expected_loss_skip) else np.nan,
        "decision": decision,
    }
