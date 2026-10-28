"""
Q, Q' 값 계산 유틸리티
"""

import numpy as np
from typing import Dict, Tuple


class QCalculator:
    """Q-System 값 계산"""

    ROCK_CLASSES = [
        (0.001, 0.01, "Exceptionally Poor", "극히 불량"),
        (0.01, 0.1, "Extremely Poor", "매우 불량"),
        (0.1, 1, "Very Poor", "불량"),
        (1, 4, "Poor", "다소 불량"),
        (4, 10, "Fair", "보통"),
        (10, 40, "Good", "양호"),
        (40, 100, "Very Good", "매우 양호"),
        (100, 400, "Extremely Good", "극히 양호"),
        (400, 1000, "Exceptionally Good", "최상"),
    ]

    @staticmethod
    def calc_Q(RQD, Jn, Jr, Ja, Jw, SRF) -> float:
        Jn = max(Jn, 0.5)
        Ja = max(Ja, 0.75)
        SRF = max(SRF, 0.5)
        return (RQD / Jn) * (Jr / Ja) * (Jw / SRF)

    @staticmethod
    def calc_Qprime(RQD, Jn, Jr, Ja) -> float:
        Jn = max(Jn, 0.5)
        Ja = max(Ja, 0.75)
        return (RQD / Jn) * (Jr / Ja)

    @classmethod
    def classify(cls, Q: float) -> Tuple[str, str]:
        for low, high, eng, kor in cls.ROCK_CLASSES:
            if low <= Q < high:
                return eng, kor
        if Q >= 1000:
            return "Exceptionally Good", "최상"
        return "Exceptionally Poor", "극히 불량"

    @staticmethod
    def Q_to_RMR(Q: float) -> Dict:
        ln_Q = np.log(max(Q, 1e-10))
        return {
            'Bieniawski (1976)': 9 * ln_Q + 44,
            'Rutledge (1978)': 5.9 * ln_Q + 43,
            'Abad et al. (1984)': 10.5 * ln_Q + 41.8,
            'Barton (1995)': 15 * np.log10(max(Q, 1e-10)) + 50,
        }