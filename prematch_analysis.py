#!/usr/bin/env python3
"""Generate an automatic pre-match analysis ficha (PNG) for a football match
using TheStatsAPI.

Usage:
    python prematch_analysis.py --home "New York Red Bulls" --away "Charlotte FC"
    python prematch_analysis.py --match_id mt_153015080
    python prematch_analysis.py --home "Real Madrid" --away "Barcelona" --date 2026-08-15

Requires the STATSAPI_KEY environment variable to hold a valid bearer token.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from api_client import StatsAPIClient, StatsAPIError
from ficha_generator import generate_ficha
from models import (
    build_score_matrix,
    btts_probabilities,
    double_chance_probabilities,
    estimate_expected_goals,
    most_likely_scorelines,
    over_under_probabilities,
    result_probabilities,
    value_edge,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("prematch_analysis")

DEFAULT_OUTPUT_DIR = "fichas"
DEFAULT_N_RECENT = 10
DEFAULT_SEARCH_WINDOW_DAYS = 21
BOOKMAKER_PREFERENCE = ["Pinnacle", "Bet365", "Betfair Exchange", "BetMGM UK", "Paddy Power"]


# ---------------------------------------------------------------------- #
# Team / match resolution
# ---------------------------------------------------------------------- #
def resolve_team(client: StatsAPIClient, name: str) -> dict | None:
    results = client.search_teams(name)
    if not results:
        return None
    for t in results:
        if t.get("name", "").lower() == name.lower():
            return t
    return results[0]


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def find_match(
    client: StatsAPIClient,
    home_id: str,
    away_id: str,
    approx_date: str | None,
    window_days: int = DEFAULT_SEARCH_WINDOW_DAYS,
) -> dict | None:
    now = datetime.now(timezone.utc)
    if approx_date:
        center = _parse_date(approx_date)
        date_from = (center - timedelta(days=window_days)).date().isoformat()
        date_to = (center + timedelta(days=window_days)).date().isoformat()
    else:
        center = now
        date_from = (now - timedelta(days=3)).date().isoformat()
        date_to = (now + timedelta(days=120)).date().isoformat()

    matches = client.list_matches(team_id=home_id, date_from=date_from, date_to=date_to)
    candidates = [m for m in matches if away_id in (m["home_team"]["id"], m["away_team"]["id"])]
    if not candidates:
        return None

    def diff(m: dict) -> float:
        try:
            match_dt = datetime.strptime(m["utc_date"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            return float("inf")
        return abs((match_dt - center).total_seconds())

    candidates.sort(key=diff)
    return candidates[0]


# ---------------------------------------------------------------------- #
# Coverage
# ---------------------------------------------------------------------- #
def get_coverage_flags(client: StatsAPIClient, competition_id: str, season_id: str) -> dict[str, bool]:
    """Return availability flags per data type; defaults to True (try-anyway) on any lookup failure."""
    default = {"team_stats": True, "xg": True, "odds": True}
    coverage = client.get_league_coverage(competition_id)
    if not coverage:
        logger.info("Coverage lookup failed for %s, will try calls directly and fall back on error.", competition_id)
        return default
    for season in coverage.get("seasons", []):
        if season.get("id") == season_id:
            data_types = season.get("data_types", {})
            return {
                "team_stats": data_types.get("team_stats", {}).get("available", True),
                "xg": data_types.get("xg", {}).get("available", True),
                "odds": data_types.get("odds", {}).get("available", True),
            }
    logger.info("Season %s not found in coverage for %s, will try calls directly.", season_id, competition_id)
    return default


# ---------------------------------------------------------------------- #
# Team stats (primary path + fallback)
# ---------------------------------------------------------------------- #
def _result_letter(gf: float, ga: float) -> str:
    if gf > ga:
        return "G"
    if gf < ga:
        return "P"
    return "E"


def stats_from_team_stats_endpoint(team_id: str, season_id: str, data: dict) -> dict[str, Any]:
    played = data.get("matches_played") or 0
    gf_avg = data["goals_for"] / played if played else 0.0
    ga_avg = data["goals_against"] / played if played else 0.0
    form_map = {"W": "G", "D": "E", "L": "P"}
    form_letters = [form_map.get(c, "E") for c in data.get("form", "")][-5:]
    return {
        "gf_home": gf_avg,
        "ga_home": ga_avg,
        "gf_away": gf_avg,
        "ga_away": ga_avg,
        "form": form_letters,
        "source": "team_stats (temporada, sin split local/visita)",
    }


def stats_from_recent_matches(
    client: StatsAPIClient,
    team_id: str,
    reference_date: str,
    n_recent: int,
) -> dict[str, Any] | None:
    matches = client.list_matches(team_id=team_id, status="finished", date_to=reference_date, per_page=100)
    if not matches:
        return None

    def match_dt(m: dict) -> datetime:
        try:
            return datetime.strptime(m["utc_date"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            return datetime.min.replace(tzinfo=timezone.utc)

    matches.sort(key=match_dt, reverse=True)
    recent = matches[:n_recent]

    home_gf, home_ga, away_gf, away_ga = [], [], [], []
    form_letters: list[str] = []

    for m in recent:
        is_home = m["home_team"]["id"] == team_id
        score = m.get("score") or {}
        real_gf = score.get("home") if is_home else score.get("away")
        real_ga = score.get("away") if is_home else score.get("home")
        if real_gf is None or real_ga is None:
            continue

        gf, ga = real_gf, real_ga
        if m.get("xg_available"):
            match_stats = client.get_match_stats(m["id"])
            xg = (match_stats or {}).get("overview", {}).get("expected_goals", {}).get("all") if match_stats else None
            if xg and xg.get("home") is not None and xg.get("away") is not None:
                gf = xg["home"] if is_home else xg["away"]
                ga = xg["away"] if is_home else xg["home"]

        if is_home:
            home_gf.append(gf)
            home_ga.append(ga)
        else:
            away_gf.append(gf)
            away_ga.append(ga)

        if len(form_letters) < 5:
            form_letters.append(_result_letter(real_gf, real_ga))

    overall_gf = home_gf + away_gf
    overall_ga = home_ga + away_ga
    if not overall_gf:
        return None

    def avg(vals: list[float], fallback: list[float]) -> float:
        return statistics.fmean(vals) if vals else (statistics.fmean(fallback) if fallback else 0.0)

    return {
        "gf_home": avg(home_gf, overall_gf),
        "ga_home": avg(home_ga, overall_ga),
        "gf_away": avg(away_gf, overall_gf),
        "ga_away": avg(away_ga, overall_ga),
        "form": list(reversed(form_letters)),
        "source": f"ultimos {len(recent)} partidos (fallback)",
    }


def get_team_analysis_stats(
    client: StatsAPIClient,
    team_id: str,
    season_id: str,
    reference_date: str,
    coverage_ok: bool,
    n_recent: int,
) -> dict[str, Any]:
    if coverage_ok:
        data = client.get_team_stats(team_id, season_id)
        if data:
            return stats_from_team_stats_endpoint(team_id, season_id, data)
        logger.info("Team stats unavailable (404/error) for %s, falling back to recent matches.", team_id)
    else:
        logger.info("Coverage says team_stats unavailable for %s, using recent-matches fallback.", team_id)

    fallback = stats_from_recent_matches(client, team_id, reference_date, n_recent)
    if fallback:
        return fallback

    logger.warning("No data at all for team %s; using neutral placeholder averages.", team_id)
    return {"gf_home": 1.2, "ga_home": 1.2, "gf_away": 1.2, "ga_away": 1.2, "form": [], "source": "sin datos (placeholder)"}


# ---------------------------------------------------------------------- #
# Odds
# ---------------------------------------------------------------------- #
def pick_bookmaker(bookmakers: list[dict]) -> dict | None:
    by_name = {b["bookmaker"]: b for b in bookmakers}
    for name in BOOKMAKER_PREFERENCE:
        if name in by_name:
            return by_name[name]
    return bookmakers[0] if bookmakers else None


def _odd(entry: dict | None) -> float | None:
    if not entry:
        return None
    val = entry.get("last_seen") or entry.get("opening")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def extract_odds(client: StatsAPIClient, match_id: str) -> dict[str, Any] | None:
    data = client.get_match_odds(match_id)
    if not data or not data.get("bookmakers"):
        return None
    book = pick_bookmaker(data["bookmakers"])
    if not book:
        return None
    markets = book.get("markets", {})
    match_odds = markets.get("match_odds", {})
    btts = markets.get("btts", {})
    double_chance = markets.get("double_chance", {})
    return {
        "bookmaker": book.get("bookmaker"),
        "match_odds": {
            "home": _odd(match_odds.get("home")),
            "draw": _odd(match_odds.get("draw")),
            "away": _odd(match_odds.get("away")),
        },
        "btts": {
            "yes": _odd(btts.get("yes")),
            "no": _odd(btts.get("no")),
        },
        "double_chance": {
            "home_draw": _odd(double_chance.get("home_draw")),
            "home_away": _odd(double_chance.get("home_away")),
            "draw_away": _odd(double_chance.get("draw_away")),
        },
    }


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #
def build_payload(
    client: StatsAPIClient,
    home: str | None = None,
    away: str | None = None,
    match_id: str | None = None,
    date: str | None = None,
    n_recent: int = DEFAULT_N_RECENT,
    rho: float = -0.05,
) -> dict[str, Any]:
    """Resolve the match and build the full analysis payload.

    Raises ValueError with a user-facing message if the match/teams can't be
    resolved, instead of exiting the process, so this can be reused from a
    web request handler.
    """
    if match_id:
        detail = client.get_match(match_id)
        if not detail:
            raise ValueError(f"No se pudo obtener el partido {match_id}.")
    else:
        if not home or not away:
            raise ValueError("Debes indicar equipo local y visitante, o un match_id.")
        home_team = resolve_team(client, home)
        away_team = resolve_team(client, away)
        if not home_team:
            raise ValueError(f"No se encontro el equipo: {home}")
        if not away_team:
            raise ValueError(f"No se encontro el equipo: {away}")
        match = find_match(client, home_team["id"], away_team["id"], date)
        if not match:
            raise ValueError(f"No se encontro un partido entre {home} y {away} cerca de la fecha indicada.")
        detail = client.get_match(match["id"])
        if not detail:
            raise ValueError(f"No se pudo obtener el detalle del partido {match['id']}.")

    match_id = detail["id"]
    competition_id = detail["competition_id"]
    season_id = detail["season_id"]
    home_team_info = detail["home_team"]
    away_team_info = detail["away_team"]
    reference_date = detail["utc_date"][:10]

    logger.info(
        "Partido resuelto: %s vs %s (%s) el %s [match_id=%s]",
        home_team_info["name"],
        away_team_info["name"],
        detail.get("competition_name", competition_id),
        reference_date,
        match_id,
    )

    coverage = get_coverage_flags(client, competition_id, season_id)

    home_stats = get_team_analysis_stats(
        client, home_team_info["id"], season_id, reference_date, coverage["team_stats"], n_recent
    )
    away_stats = get_team_analysis_stats(
        client, away_team_info["id"], season_id, reference_date, coverage["team_stats"], n_recent
    )

    odds = None
    if detail.get("odds_available") and coverage["odds"]:
        odds = extract_odds(client, match_id)
    elif detail.get("odds_available"):
        logger.info("Coverage marca odds no disponibles para esta temporada; se omite la llamada de cuotas.")

    lambda_home, lambda_away = estimate_expected_goals(
        home_stats["gf_home"], home_stats["ga_home"], away_stats["gf_away"], away_stats["ga_away"]
    )
    matrix = build_score_matrix(lambda_home, lambda_away, rho=rho)
    result = result_probabilities(matrix)
    dc = double_chance_probabilities(result)
    btts = btts_probabilities(matrix)
    ou = over_under_probabilities(matrix)
    top_scores = most_likely_scorelines(matrix, 5)

    edges: dict[str, float | None] = {}
    if odds:
        mo = odds["match_odds"]
        edges["home"] = value_edge(result["home"], mo["home"])
        edges["draw"] = value_edge(result["draw"], mo["draw"])
        edges["away"] = value_edge(result["away"], mo["away"])
        edges["btts_yes"] = value_edge(btts["yes"], odds["btts"]["yes"])
        edges["btts_no"] = value_edge(btts["no"], odds["btts"]["no"])

    payload = {
        "home_team": home_team_info,
        "away_team": away_team_info,
        "competition_name": detail.get("competition_name", competition_id),
        "date_display": reference_date,
        "venue": (detail.get("venue") or {}).get("name"),
        "home_form": home_stats["form"],
        "away_form": away_stats["form"],
        "home_stats": home_stats,
        "away_stats": away_stats,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "model": {
            "result": result,
            "double_chance": dc,
            "btts": btts,
            "over_under": ou,
            "top_scorelines": top_scores,
        },
        "odds": odds,
        "edges": edges,
    }
    return payload


def run(args: argparse.Namespace) -> Path:
    client = StatsAPIClient()
    try:
        payload = build_payload(
            client,
            home=args.home,
            away=args.away,
            match_id=args.match_id,
            date=args.date,
            n_recent=args.n_recent,
            rho=args.rho,
        )
    except ValueError as exc:
        sys.exit(str(exc))

    home_team_info = payload["home_team"]
    away_team_info = payload["away_team"]
    result = payload["model"]["result"]
    btts = payload["model"]["btts"]
    odds = payload["odds"]

    output_dir = Path(args.output_dir)
    safe_home = home_team_info["name"].replace(" ", "_")
    safe_away = away_team_info["name"].replace(" ", "_")
    output_path = output_dir / f"{safe_home}_vs_{safe_away}_{payload['date_display']}.png"
    generate_ficha(payload, output_path)

    print(f"\nFicha generada: {output_path}")
    print(f"1X2 -> Local {result['home']*100:.1f}%  Empate {result['draw']*100:.1f}%  Visita {result['away']*100:.1f}%")
    print(f"BTTS -> Si {btts['yes']*100:.1f}%  No {btts['no']*100:.1f}%")
    if odds:
        print(f"Cuotas ({odds['bookmaker']}): 1={odds['match_odds']['home']} X={odds['match_odds']['draw']} 2={odds['match_odds']['away']}")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera una ficha visual de analisis pre-partido.")
    parser.add_argument("--home", help="Nombre del equipo local")
    parser.add_argument("--away", help="Nombre del equipo visitante")
    parser.add_argument("--match_id", help="ID de partido conocido (mt_...), evita la busqueda por nombre/fecha")
    parser.add_argument("--date", help="Fecha aproximada del partido (YYYY-MM-DD)")
    parser.add_argument("--n_recent", type=int, default=DEFAULT_N_RECENT, help="Partidos recientes a usar en el fallback (default 10)")
    parser.add_argument("--output_dir", default=DEFAULT_OUTPUT_DIR, help="Carpeta de salida para la ficha (default fichas/)")
    parser.add_argument("--rho", type=float, default=-0.05, help="Parametro rho de la correccion Dixon-Coles (default -0.05)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        run(parse_args())
    except StatsAPIError as exc:
        sys.exit(str(exc))
