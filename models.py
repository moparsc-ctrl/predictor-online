"""Poisson goal-expectancy model with a Dixon-Coles low-score correction.

This is a deliberately simple, transparent model meant for an informational
pre-match ficha — not a calibrated trading model. Two building blocks:

1. Expected goals (lambda_home, lambda_away) from each team's own scoring
   record, split by home/away, averaged against the opponent's conceding
   record on the same side.
2. A Dixon-Coles `rho` adjustment on the raw Poisson score matrix, which
   corrects the well-known tendency of independent Poisson models to
   under-price low, correlated scorelines (0-0, 1-0, 0-1, 1-1).
"""

from __future__ import annotations

import math

MIN_EXPECTED_GOALS = 0.1
DEFAULT_RHO = -0.05
DEFAULT_MAX_GOALS = 10
OVER_UNDER_LINES = [0.5, 1.5, 2.5, 3.5, 4.5]


def estimate_expected_goals(
    home_attack_home: float,
    home_defense_home: float,
    away_attack_away: float,
    away_defense_away: float,
) -> tuple[float, float]:
    """Blend each team's own record with the opponent's record on the same side.

    `home_attack_home` = home team's avg goals (or xG) FOR when playing at home.
    `home_defense_home` = home team's avg goals (or xG) AGAINST when playing at home.
    `away_attack_away` = away team's avg goals (or xG) FOR when playing away.
    `away_defense_away` = away team's avg goals (or xG) AGAINST when playing away.
    """
    lambda_home = (home_attack_home + away_defense_away) / 2
    lambda_away = (away_attack_away + home_defense_home) / 2
    return max(lambda_home, MIN_EXPECTED_GOALS), max(lambda_away, MIN_EXPECTED_GOALS)


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def dixon_coles_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def build_score_matrix(
    lambda_home: float,
    lambda_away: float,
    rho: float = DEFAULT_RHO,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> list[list[float]]:
    """Return matrix[home_goals][away_goals] of probabilities, normalized to sum to 1."""
    matrix = [
        [
            poisson_pmf(x, lambda_home) * poisson_pmf(y, lambda_away) * dixon_coles_tau(x, y, lambda_home, lambda_away, rho)
            for y in range(max_goals + 1)
        ]
        for x in range(max_goals + 1)
    ]
    total = sum(sum(row) for row in matrix)
    if total <= 0:
        return matrix
    return [[cell / total for cell in row] for row in matrix]


def result_probabilities(matrix: list[list[float]]) -> dict[str, float]:
    home = draw = away = 0.0
    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            if x > y:
                home += p
            elif x == y:
                draw += p
            else:
                away += p
    return {"home": home, "draw": draw, "away": away}


def double_chance_probabilities(result: dict[str, float]) -> dict[str, float]:
    return {
        "home_or_draw": result["home"] + result["draw"],
        "home_or_away": result["home"] + result["away"],
        "draw_or_away": result["draw"] + result["away"],
    }


def btts_probabilities(matrix: list[list[float]]) -> dict[str, float]:
    yes = sum(p for x, row in enumerate(matrix) for y, p in enumerate(row) if x > 0 and y > 0)
    return {"yes": yes, "no": 1 - yes}


def over_under_probabilities(
    matrix: list[list[float]], lines: list[float] = OVER_UNDER_LINES
) -> dict[float, dict[str, float]]:
    out: dict[float, dict[str, float]] = {}
    for line in lines:
        over = sum(p for x, row in enumerate(matrix) for y, p in enumerate(row) if x + y > line)
        out[line] = {"over": over, "under": 1 - over}
    return out


def most_likely_scorelines(matrix: list[list[float]], top_n: int = 5) -> list[tuple[int, int, float]]:
    flat = [(x, y, p) for x, row in enumerate(matrix) for y, p in enumerate(row)]
    flat.sort(key=lambda t: t[2], reverse=True)
    return flat[:top_n]


def implied_probability(decimal_odd: float) -> float:
    return 1 / decimal_odd if decimal_odd and decimal_odd > 0 else 0.0


def value_edge(model_prob: float, decimal_odd: float | None) -> float | None:
    """Model probability minus the bookmaker's raw implied probability (no overround removal).

    Positive = model likes the outcome more than the market price implies. Informational only.
    """
    if not decimal_odd:
        return None
    return model_prob - implied_probability(decimal_odd)
