"""Rules-based betting-angle recommendation text for the recent-form ficha.

Built entirely from numbers the app already computes (1X2/double-chance
probabilities from the Poisson+Dixon-Coles model, recent goal difference,
xG, and recent-form points) — no external LLM call, so it's free and
instant. Mirrors the recommendation engine used in the sister Next.js app.
"""

from __future__ import annotations

from typing import Any

# A single 1X2 outcome is treated as a "clear favorite" once it clears this
# probability and has a meaningful gap over the next-most-likely outcome.
CLEAR_FAVORITE_PROBABILITY = 0.50
CLEAR_FAVORITE_GAP = 0.12


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _signed(n: float) -> str:
    return f"+{n:.0f}" if n > 0 else f"{n:.0f}"


def build_betting_recommendation(
    home_name: str,
    away_name: str,
    result: dict[str, float],
    double_chance: dict[str, float],
    btts: dict[str, float],
    home_xg: float,
    away_xg: float,
    home_goal_diff: float,
    away_goal_diff: float,
    home_points: int,
    away_points: int,
    home_games_used: int,
    away_games_used: int,
) -> dict[str, Any]:
    sentences: list[str] = []

    if home_goal_diff == away_goal_diff:
        sentences.append(
            f"Partido parejo en el balance reciente: ambos con la misma diferencia de gol ({_signed(home_goal_diff)})."
        )
    else:
        better = home_name if home_goal_diff > away_goal_diff else away_name
        sentences.append(
            f"{better} llega con mejor diferencia de gol reciente "
            f"({_signed(home_goal_diff)} vs {_signed(away_goal_diff)})."
        )

    home_xg_r, away_xg_r = round(home_xg, 1), round(away_xg, 1)
    if home_xg_r == away_xg_r:
        sentences.append(f"El xG proyectado es practicamente identico ({home_xg_r:.1f} cada uno).")
    elif abs(home_xg_r - away_xg_r) < 0.3:
        sentences.append(f"El xG proyectado es similar ({home_xg_r:.1f} vs {away_xg_r:.1f}).")
    else:
        more_xg = home_name if home_xg > away_xg else away_name
        sentences.append(f"{more_xg} proyecta mas goles esperados ({home_xg_r:.1f} vs {away_xg_r:.1f}).")

    if home_games_used > 0 or away_games_used > 0:
        home_max = home_games_used * 3
        away_max = away_games_used * 3
        if home_points == away_points:
            sentences.append(
                "Ambos llegan con puntos similares en su muestra reciente "
                f"({home_points} de {home_max} vs {away_points} de {away_max})."
            )
        else:
            leader = home_name if home_points > away_points else away_name
            sentences.append(
                f"{leader} suma mas puntos en su muestra reciente "
                f"({home_points} de {home_max} vs {away_points} de {away_max})."
            )

    sentences.append(
        f"El modelo Poisson reparte el resultado en {_pct(result['home'])} / {_pct(result['draw'])} / "
        f"{_pct(result['away'])} (local / empate / visitante)."
    )

    favorite_prob = max(result["home"], result["away"])
    second_prob = min(max(result["home"], result["draw"]), max(result["away"], result["draw"]))
    favorite_is_home = result["home"] >= result["away"]
    is_clear_favorite = (
        favorite_prob >= CLEAR_FAVORITE_PROBABILITY and (favorite_prob - second_prob) >= CLEAR_FAVORITE_GAP
    )

    if is_clear_favorite:
        favorite_name = home_name if favorite_is_home else away_name
        market = f"Victoria de {favorite_name}"
        probability = favorite_prob
        sentences.append(
            f"{favorite_name} se perfila como favorito claro ({_pct(favorite_prob)}), por lo que el resultado "
            "directo es la opcion con mejor relacion entre probabilidad y cuota esperada."
        )
    else:
        # Tight match: lean the double-chance pick toward whichever side has
        # the edge in win probability, breaking ties with recent points,
        # then goal difference, then xG.
        lean_home = result["home"] > result["away"]
        tied = abs(result["home"] - result["away"]) < 0.01
        if tied:
            if home_points != away_points:
                lean_home = home_points > away_points
            elif home_goal_diff != away_goal_diff:
                lean_home = home_goal_diff > away_goal_diff
            else:
                lean_home = home_xg >= away_xg

        if lean_home:
            market = f"Doble oportunidad 1X ({home_name} o empate)"
            probability = double_chance["home_or_draw"]
            sentences.append(
                f"La 1X (~{_pct(double_chance['home_or_draw'])}) da un margen adicional apoyado en la ligera "
                f"ventaja de {home_name}; la X2 (~{_pct(double_chance['draw_or_away'])}) ofrece la misma "
                "cobertura si prefieres el visitante."
            )
        else:
            market = f"Doble oportunidad X2 (empate o victoria de {away_name})"
            probability = double_chance["draw_or_away"]
            sentences.append(
                f"La X2 (~{_pct(double_chance['draw_or_away'])}) da un margen adicional apoyado en la ligera "
                f"ventaja de {away_name}; la 1X (~{_pct(double_chance['home_or_draw'])}) ofrece la misma "
                "cobertura si prefieres el local."
            )

    if btts["yes"] >= 0.68:
        sentences.append(
            f"Dato extra: ambos equipos anotan (BTTS) en el {_pct(btts['yes'])} de las simulaciones, "
            "una alternativa a considerar."
        )
    elif btts["yes"] <= 0.32:
        sentences.append(
            f"Dato extra: el modelo ve poco probable que ambos anoten "
            f"(BTTS \"No\" en el {_pct(btts['no'])} de las simulaciones)."
        )

    return {"market": market, "probability": probability, "rationale": " ".join(sentences)}
