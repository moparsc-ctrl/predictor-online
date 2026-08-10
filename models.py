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

# Reference values treated as a "100" on the 0-100 attack/defense rating scale,
# calibrated to typical top-division per-match volumes. Deliberately simple
# (linear, capped) rather than league-relative — informational, not a model input.
RATING_XG_REF = 2.5
RATING_SHOTS_REF = 20.0
RATING_SOT_REF = 8.0
RATING_WEIGHTS = {"xg": 0.5, "shots": 0.25, "sot": 0.25}

RATING_LEVEL_STRONG = 70.0
RATING_LEVEL_MEDIUM = 45.0


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


def project_combined_stat(
    home_for: float | None,
    away_against: float | None,
    away_for: float | None,
    home_against: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Projects a single match stat (shots, shots on target, corners...) for
    one specific fixture by averaging each side's own "for" rate with the
    opponent's "against" rate on the same stat, e.g. projected home shots =
    avg(home shots-for, away shots-against). Returns (home, away, total).
    """
    home = None if home_for is None or away_against is None else (home_for + away_against) / 2
    away = None if away_for is None or home_against is None else (away_for + home_against) / 2
    total = None if home is None or away is None else home + away
    return home, away, total


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rating_component(avg_value: float | None, reference: float) -> float | None:
    if avg_value is None:
        return None
    return max(0.0, min(1.0, avg_value / reference))


def rating_level(score: float) -> str:
    if score >= RATING_LEVEL_STRONG:
        return "fuerte"
    if score >= RATING_LEVEL_MEDIUM:
        return "medio"
    return "debil"


def attack_defense_rating(
    xg_for: list[float],
    shots_for: list[float],
    sot_for: list[float],
    xg_against: list[float],
    shots_against: list[float],
    sot_against: list[float],
) -> dict[str, float | str]:
    """Blend xG, shots and shots-on-target (for and against) into 0-100 attack/defense scores.

    Each list holds one value per recent match (already filtered for None). Missing
    stat types just drop out of the weighted average rather than zeroing the score.
    """
    w = RATING_WEIGHTS

    def blend(avg_xg: float | None, avg_shots: float | None, avg_sot: float | None) -> float:
        parts = [
            (w["xg"], _rating_component(avg_xg, RATING_XG_REF)),
            (w["shots"], _rating_component(avg_shots, RATING_SHOTS_REF)),
            (w["sot"], _rating_component(avg_sot, RATING_SOT_REF)),
        ]
        used = [(weight, value) for weight, value in parts if value is not None]
        total_weight = sum(weight for weight, _ in used) or 1.0
        return 100 * sum(weight * value for weight, value in used) / total_weight

    attack = blend(_avg(xg_for), _avg(shots_for), _avg(sot_for))
    defense = 100 - blend(_avg(xg_against), _avg(shots_against), _avg(sot_against))
    attack = max(0.0, min(100.0, attack))
    defense = max(0.0, min(100.0, defense))

    return {
        "attack": attack,
        "defense": defense,
        "level": rating_level((attack + defense) / 2),
    }
