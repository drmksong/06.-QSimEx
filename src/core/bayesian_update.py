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

    Parameters
    ----------
    prior_suitable : float
        적합 암반(Z=1)일 사전 확률 P(Z=1). 지역적 통계나 이전 구간 데이터를 통해 설정.
    observed_borehole_class : int
        시추공 관측 결과 (1: 적합 판단, 0: 부적합 판단).
    sensitivity : float
        민감도 P(B=1 | Z=1). 실제 적합할 때 시추공이 적합하다고 할 확률.
    specificity : float
        특이도 P(B=0 | Z=0). 실제 부적합할 때 시추공이 부적합하다고 할 확률.

    Returns
    -------
    float
        사후 확률 P(Z=1 | B_obs). 분모가 0일 경우 NaN 반환.

    Notes
    -----
    [암반 등급(Rock Grade) 확장을 위한 가이드]
    향후 Very Poor ~ Very Good 등의 등급형 베이지안 분석으로 확장할 경우:
    1. 사전 확률(Prior): 단일 float 대신 N개 등급에 대한 확률 분포 벡터 [p1, p2, ..., pN]를 입력받습니다.
    2. 가능도(Likelihood): 민감도/특이도 대신 '혼동행렬(Confusion Matrix)'을 Likelihood Matrix L로 사용합니다.
       L[i, j] = P(Borehole Grade = i | Actual Face Grade = j)
    3. 업데이트 식:
       - 분자(Vector): Numerator[j] = L[observed_i, j] * Prior[j]
       - 분모(Scalar): Evidence = Sum(Numerator)
       - 사후확률(Vector): Posterior[j] = Numerator[j] / Evidence
    """
    p = prior_suitable

    # 관측 결과에 따른 가능도(Likelihood) 할당
    if observed_borehole_class == 1:
        # 시추공이 '적합'이라고 함
        likelihood_suitable = sensitivity  # P(B=1 | Z=1)
        likelihood_unsuitable = 1.0 - specificity  # P(B=1 | Z=0), False Positive Rate
    elif observed_borehole_class == 0:
        # 시추공이 '부적합'이라고 함
        likelihood_suitable = 1.0 - sensitivity  # P(B=0 | Z=1), False Negative Rate
        likelihood_unsuitable = specificity  # P(B=0 | Z=0)
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

    Parameters
    ----------
    posterior_suitable : float
        업데이트된 암반 적합성 사후 확률 P(suitable | data).
    cost_config : DecisionCost, optional
        비용 구조 설정. None일 경우 기본값(10:1)을 사용합니다.

    Returns
    -------
    dict
        결정 결과 (decision: 'excavate' 또는 'skip') 및 기대 손실 정보.
    """
    if cost_config is None:
        cost_config = DecisionCost()

    p = posterior_suitable
    c_fp = cost_config.cost_fp
    c_fn = cost_config.cost_fn

    # 기대 손실 계산
    expected_loss_excavate = c_fp * (1.0 - p)
    expected_loss_skip = c_fn * p

    # 손실이 최소화되는 방향으로 결정
    decision = "excavate" if expected_loss_excavate < expected_loss_skip else "skip"

    return {
        "posterior_suitable": float(p),
        "p_threshold": float(cost_config.p_threshold),
        "expected_loss_excavate": float(expected_loss_excavate),
        "expected_loss_skip": float(expected_loss_skip),
        "decision": decision,
    }
