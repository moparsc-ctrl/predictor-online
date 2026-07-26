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
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from api_client import StatsAPIClient, StatsAPIError
from ficha_generator import generate_ficha, generate_form_ficha, generate_h2h_ficha, generate_match_by_match_ficha
from models import (
    attack_defense_rating,
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
DEFAULT_FORM_N = 5
DEFAULT_H2H_N = 5
DEFAULT_SEARCH_WINDOW_DAYS = 21
BOOKMAKER_PREFERENCE = ["Pinnacle", "Bet365", "Betfair Exchange", "BetMGM UK", "Paddy Power"]


# ---------------------------------------------------------------------- #
# Team / match resolution
# ---------------------------------------------------------------------- #
def _normalize_name(name: str) -> str:
    """Lowercase and strip accents, e.g. 'FC Juárez' -> 'fc juarez'.

    TheStatsAPI's team search is accent-sensitive and its data isn't
    consistently accented across youth/reserve vs. senior team names, so a
    plain-ASCII search for a team like Juarez can miss the real one. Match
    detail payloads carry the correctly-accented name regardless, so we fall
    back to comparing those directly instead of trusting search results.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def resolve_team_candidates(client: StatsAPIClient, name: str, limit: int = 5) -> list[dict]:
    """Search results for `name`, exact (accent-insensitive) matches first.

    Team search can return several same-named or oddly-ranked entries (a
    reserve squad, a same-named club in another country, a duplicate row) and
    there's no reliable way to tell which one is "the" team from the name
    alone. Callers should try these in order against find_match rather than
    trusting the first result.
    """
    results = client.search_teams(name)
    if not results:
        return []
    target = _normalize_name(name)
    exact = [t for t in results if _normalize_name(t.get("name", "")) == target]
    rest = [t for t in results if t not in exact]
    return (exact + rest)[:limit]


def resolve_team(client: StatsAPIClient, name: str) -> dict | None:
    candidates = resolve_team_candidates(client, name, limit=1)
    return candidates[0] if candidates else None


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def find_match(
    client: StatsAPIClient,
    home_id: str,
    away_id: str,
    approx_date: str | None,
    home_name: str | None = None,
    away_name: str | None = None,
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

    def closest(candidates: list[dict]) -> dict | None:
        if not candidates:
            return None

        def diff(m: dict) -> float:
            try:
                match_dt = datetime.strptime(m["utc_date"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            except (ValueError, KeyError):
                return float("inf")
            return abs((match_dt - center).total_seconds())

        return min(candidates, key=diff)

    def fuzzy_filter(matches: list[dict], target_name: str) -> list[dict]:
        target = _normalize_name(target_name)
        return [
            m
            for m in matches
            if target in _normalize_name(m["home_team"]["name"]) or target in _normalize_name(m["away_team"]["name"])
        ]

    home_matches = client.list_matches(team_id=home_id, date_from=date_from, date_to=date_to)
    candidates = [m for m in home_matches if away_id in (m["home_team"]["id"], m["away_team"]["id"])]
    match = closest(candidates)
    if match:
        return match

    # ID-based lookup can miss real matches when team search resolved the
    # wrong (e.g. accent-mismatched or duplicate) team id. Fall back to
    # matching by name directly against the fixtures we already have.
    if away_name:
        match = closest(fuzzy_filter(home_matches, away_name))
        if match:
            return match

    if home_name and away_id != home_id:
        away_matches = client.list_matches(team_id=away_id, date_from=date_from, date_to=date_to)
        match = closest(fuzzy_filter(away_matches, home_name))
        if match:
            return match

    return None


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


# ---------------------------------------------------------------------- #
# Recent match records (form/rating ficha)
# ---------------------------------------------------------------------- #
def get_recent_match_records(
    client: StatsAPIClient, team_id: str, reference_date: str, n: int = 5
) -> list[dict[str, Any]]:
    """Last n finished matches for team_id: opponent, score and shot/corner/xG stats for both sides."""
    matches = client.list_matches(team_id=team_id, status="finished", date_to=reference_date, per_page=100)
    if not matches:
        return []

    def match_dt(m: dict) -> datetime:
        try:
            return datetime.strptime(m["utc_date"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            return datetime.min.replace(tzinfo=timezone.utc)

    matches.sort(key=match_dt, reverse=True)

    records: list[dict[str, Any]] = []
    for m in matches[:n]:
        is_home = m["home_team"]["id"] == team_id
        opponent = m["away_team"] if is_home else m["home_team"]
        score = m.get("score") or {}
        team_goals = score.get("home") if is_home else score.get("away")
        opp_goals = score.get("away") if is_home else score.get("home")
        if team_goals is None or opp_goals is None:
            continue

        match_stats = client.get_match_stats(m["id"]) or {}
        overview = match_stats.get("overview", {})

        def side(stat_key: str) -> tuple[float | None, float | None]:
            block = (overview.get(stat_key) or {}).get("all") or {}
            home_v, away_v = block.get("home"), block.get("away")
            return (home_v, away_v) if is_home else (away_v, home_v)

        team_shots, opp_shots = side("total_shots")
        team_sot, opp_sot = side("shots_on_target")
        team_corners, opp_corners = side("corner_kicks")
        team_xg, opp_xg = side("expected_goals")

        records.append(
            {
                "opponent_name": opponent["name"],
                "is_home": is_home,
                "team_goals": team_goals,
                "opp_goals": opp_goals,
                "team_shots": team_shots,
                "opp_shots": opp_shots,
                "team_sot": team_sot,
                "opp_sot": opp_sot,
                "team_corners": team_corners,
                "opp_corners": opp_corners,
                "team_xg": team_xg,
                "opp_xg": opp_xg,
            }
        )
    return records


def rating_from_records(records: list[dict[str, Any]]) -> dict[str, float | str]:
    def col(key: str) -> list[float]:
        return [r[key] for r in records if r[key] is not None]

    return attack_defense_rating(
        xg_for=col("team_xg"),
        shots_for=col("team_shots"),
        sot_for=col("team_sot"),
        xg_against=col("opp_xg"),
        shots_against=col("opp_shots"),
        sot_against=col("opp_sot"),
    )


def get_head_to_head(
    client: StatsAPIClient,
    home_id: str,
    away_id: str,
    reference_date: str,
    n: int = 5,
    exclude_match_id: str | None = None,
) -> list[dict[str, Any]]:
    """Last n finished meetings between these two teams (any competition), most recent first."""
    matches = client.list_matches(team_id=home_id, status="finished", date_to=reference_date, per_page=100)
    if not matches:
        return []

    def match_dt(m: dict) -> datetime:
        try:
            return datetime.strptime(m["utc_date"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            return datetime.min.replace(tzinfo=timezone.utc)

    h2h = []
    for m in matches:
        if m["id"] == exclude_match_id:
            continue
        if away_id not in (m["home_team"]["id"], m["away_team"]["id"]):
            continue
        score = m.get("score") or {}
        if score.get("home") is None or score.get("away") is None:
            continue
        h2h.append(m)
    h2h.sort(key=match_dt, reverse=True)

    comp_names: dict[str, str] = {}

    def comp_name(comp_id: str) -> str:
        if comp_id not in comp_names:
            coverage = client.get_league_coverage(comp_id)
            comp_names[comp_id] = (coverage or {}).get("name") or comp_id
        return comp_names[comp_id]

    records = []
    for m in h2h[:n]:
        score = m["score"]
        records.append(
            {
                "date": m["utc_date"][:10],
                "competition_name": comp_name(m["competition_id"]),
                "home_id": m["home_team"]["id"],
                "home_name": m["home_team"]["name"],
                "away_id": m["away_team"]["id"],
                "away_name": m["away_team"]["name"],
                "home_goals": score["home"],
                "away_goals": score["away"],
            }
        )
    return records


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
        home_candidates = resolve_team_candidates(client, home)
        away_candidates = resolve_team_candidates(client, away)
        if not home_candidates:
            raise ValueError(f"No se encontro el equipo: {home}")
        if not away_candidates:
            raise ValueError(f"No se encontro el equipo: {away}")

        # Team search can rank the wrong same-named club first (reserve
        # squad, different country, duplicate row), so try candidates in
        # order and only trust a pairing once it resolves to a real fixture.
        match = None
        home_team, away_team = home_candidates[0], away_candidates[0]
        for hc in home_candidates:
            for ac in away_candidates:
                match = find_match(client, hc["id"], ac["id"], date, home_name=home, away_name=away)
                if match:
                    home_team, away_team = hc, ac
                    break
            if match:
                break
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

    home_recent = get_recent_match_records(client, home_team_info["id"], reference_date, DEFAULT_FORM_N)
    away_recent = get_recent_match_records(client, away_team_info["id"], reference_date, DEFAULT_FORM_N)
    home_rating = rating_from_records(home_recent)
    away_rating = rating_from_records(away_recent)
    head_to_head = get_head_to_head(
        client, home_team_info["id"], away_team_info["id"], reference_date, DEFAULT_H2H_N, exclude_match_id=match_id
    )

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
        "home_recent_matches": home_recent,
        "away_recent_matches": away_recent,
        "home_rating": home_rating,
        "away_rating": away_rating,
        "form_n": DEFAULT_FORM_N,
        "head_to_head": head_to_head,
        "h2h_n": DEFAULT_H2H_N,
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
    base_name = f"{safe_home}_vs_{safe_away}_{payload['date_display']}"
    output_path = output_dir / f"{base_name}.png"
    generate_ficha(payload, output_path)
    generate_form_ficha(payload, output_dir / f"{base_name}_perfil.png")
    generate_match_by_match_ficha(payload, output_dir / f"{base_name}_partidos.png")
    generate_h2h_ficha(payload, output_dir / f"{base_name}_h2h.png")

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
