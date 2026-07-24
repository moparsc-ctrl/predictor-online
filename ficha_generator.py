"""Renders the pre-match analysis ficha as a PNG using Pillow.

No external assets required — team "logos" are drawn as colored initials
circles since the API does not expose crest URLs.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
MARGIN = 48
BG = (16, 20, 33)
CARD_BG = (26, 31, 48)
CARD_BG_ALT = (33, 39, 59)
TEXT = (235, 237, 242)
SUBTEXT = (150, 158, 176)
ACCENT_HOME = (77, 163, 255)
ACCENT_AWAY = (255, 138, 76)
GREEN = (68, 201, 122)
RED = (235, 87, 87)
GRAY = (120, 128, 148)
GOLD = (240, 190, 90)

FORM_COLORS = {"G": GREEN, "E": GRAY, "P": RED}

FONT_DIRS = [Path(r"C:\Windows\Fonts")]
BOLD_CANDIDATES = ["segoeuib.ttf", "arialbd.ttf", "seguisb.ttf"]
REGULAR_CANDIDATES = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]


def _find_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for folder in FONT_DIRS:
        for name in candidates:
            path = folder / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _find_font(BOLD_CANDIDATES if bold else REGULAR_CANDIDATES, size)


def _text_w(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont) -> int:
    return draw.textlength(text, font=f)


def _rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _center_text(draw, cx, y, text, f, fill):
    w = _text_w(draw, text, f)
    draw.text((cx - w / 2, y), text, font=f, fill=fill)


def _bar(draw, x, y, w, h, frac, color, bg=(52, 58, 79)):
    _rounded_rect(draw, (x, y, x + w, y + h), h // 2, bg)
    fw = max(h, int(w * max(0.0, min(1.0, frac))))
    if frac > 0:
        _rounded_rect(draw, (x, y, x + fw, y + h), h // 2, color)


def _team_badge(draw, cx, cy, radius, name, color):
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "?"
    f = font(int(radius * 0.8), bold=True)
    _center_text(draw, cx, cy - radius * 0.55, initials, f, (16, 20, 33))


def _form_row(draw, x, y, form_letters: list[str], side: str):
    f = font(20, bold=True)
    d = 34
    gap = 10
    letters = form_letters[-5:]
    total_w = len(letters) * d + max(0, len(letters) - 1) * gap
    start_x = x if side == "left" else x - total_w
    for i, letter in enumerate(letters):
        cx0 = start_x + i * (d + gap)
        color = FORM_COLORS.get(letter, GRAY)
        draw.ellipse((cx0, y, cx0 + d, y + d), fill=color)
        _center_text(draw, cx0 + d / 2, y + d / 2 - 12, letter, f, (16, 20, 33))


def _section_title(draw, y, text) -> int:
    f = font(24, bold=True)
    draw.text((MARGIN, y), text.upper(), font=f, fill=SUBTEXT)
    return y + 36


def _stat_row(draw, y, label, home_val, away_val, fmt="{:.2f}") -> int:
    f = font(22)
    fb = font(22, bold=True)
    draw.text((MARGIN, y), fmt.format(home_val), font=fb, fill=ACCENT_HOME)
    _center_text(draw, WIDTH / 2, y, label, f, SUBTEXT)
    away_text = fmt.format(away_val)
    w = _text_w(draw, away_text, fb)
    draw.text((WIDTH - MARGIN - w, y), away_text, font=fb, fill=ACCENT_AWAY)
    return y + 34


def _prob_bar_row(draw, y, label, home_p, draw_p, away_p) -> int:
    f = font(20)
    draw.text((MARGIN, y), label, font=f, fill=TEXT)
    y += 28
    bar_w = WIDTH - 2 * MARGIN
    seg_home = int(bar_w * home_p)
    seg_draw = int(bar_w * draw_p)
    h = 30
    x = MARGIN
    _rounded_rect(draw, (x, y, x + bar_w, y + h), 6, (52, 58, 79))
    draw.rectangle((x, y, x + seg_home, y + h), fill=ACCENT_HOME)
    draw.rectangle((x + seg_home, y, x + seg_home + seg_draw, y + h), fill=GRAY)
    draw.rectangle((x + seg_home + seg_draw, y, x + bar_w, y + h), fill=ACCENT_AWAY)
    fs = font(16, bold=True)
    labels = [(seg_home, home_p, "1"), (seg_draw, draw_p, "X"), (bar_w - seg_home - seg_draw, away_p, "2")]
    cursor = x
    for seg_w, p, tag in labels:
        if seg_w > 40:
            _center_text(draw, cursor + seg_w / 2, y + 6, f"{tag} {_pct(p)}", fs, (16, 20, 33))
        cursor += seg_w
    return y + h + 18


def _odds_vs_model_row(draw, y, label, model_p, odd, edge) -> int:
    f = font(20)
    fb = font(20, bold=True)
    draw.text((MARGIN, y), label, font=f, fill=TEXT)
    model_txt = f"Modelo {_pct(model_p)}"
    draw.text((WIDTH - MARGIN - 380, y), model_txt, font=fb, fill=TEXT)
    if odd is not None:
        odd_txt = f"Cuota {odd:.2f}"
        draw.text((WIDTH - MARGIN - 210, y), odd_txt, font=fb, fill=SUBTEXT)
    if edge is not None:
        color = GREEN if edge > 0 else RED
        sign = "+" if edge > 0 else ""
        edge_txt = f"{sign}{edge * 100:.1f}%"
        w = _text_w(draw, edge_txt, fb)
        draw.text((WIDTH - MARGIN - w, y), edge_txt, font=fb, fill=color)
    return y + 34


def _render_ficha(payload: dict[str, Any]) -> Image.Image:
    canvas_h = 2400
    img = Image.new("RGB", (WIDTH, canvas_h), BG)
    draw = ImageDraw.Draw(img)

    home = payload["home_team"]
    away = payload["away_team"]
    y = MARGIN

    # Header
    f_comp = font(20)
    _center_text(draw, WIDTH / 2, y, payload.get("competition_name", ""), f_comp, SUBTEXT)
    y += 30
    f_date = font(18)
    date_line = payload.get("date_display", "")
    venue = payload.get("venue")
    if venue:
        date_line += f"  ·  {venue}"
    _center_text(draw, WIDTH / 2, y, date_line, f_date, SUBTEXT)
    y += 50

    badge_r = 60
    badge_y = y + badge_r
    _team_badge(draw, MARGIN + badge_r, badge_y, badge_r, home["name"], ACCENT_HOME)
    _team_badge(draw, WIDTH - MARGIN - badge_r, badge_y, badge_r, away["name"], ACCENT_AWAY)
    f_vs = font(28, bold=True)
    _center_text(draw, WIDTH / 2, badge_y - 16, "VS", f_vs, TEXT)

    f_name = font(24, bold=True)
    draw.text((MARGIN, badge_y + badge_r + 14), home["name"], font=f_name, fill=TEXT)
    away_name_w = _text_w(draw, away["name"], f_name)
    draw.text((WIDTH - MARGIN - away_name_w, badge_y + badge_r + 14), away["name"], font=f_name, fill=TEXT)
    y = badge_y + badge_r + 54

    # Form
    y = _section_title(draw, y, "Forma reciente (ultimos 5)")
    _form_row(draw, MARGIN, y, payload.get("home_form", []), "left")
    _form_row(draw, WIDTH - MARGIN, y, payload.get("away_form", []), "right")
    y += 56

    # Goal averages
    y = _section_title(draw, y, "Promedio de goles")
    hs = payload["home_stats"]
    aws = payload["away_stats"]
    y = _stat_row(draw, y, "A favor (local / visita)", hs["gf_home"], aws["gf_away"])
    y = _stat_row(draw, y, "En contra (local / visita)", hs["ga_home"], aws["ga_away"])
    src_note = f"Fuente: {hs.get('source', '?')} / {aws.get('source', '?')}"
    f_small = font(15)
    _center_text(draw, WIDTH / 2, y + 6, src_note, f_small, SUBTEXT)
    y += 40

    # Model probabilities
    model = payload["model"]
    y = _section_title(draw, y, f"Modelo (Poisson + Dixon-Coles, xG {payload.get('lambda_home', 0):.2f} - {payload.get('lambda_away', 0):.2f})")
    result = model["result"]
    y = _prob_bar_row(draw, y, "Resultado 1X2", result["home"], result["draw"], result["away"])

    dc = model["double_chance"]
    f = font(20)
    dc_line = f"Doble oportunidad:  1X {_pct(dc['home_or_draw'])}   12 {_pct(dc['home_or_away'])}   X2 {_pct(dc['draw_or_away'])}"
    draw.text((MARGIN, y), dc_line, font=f, fill=TEXT)
    y += 34

    btts = model["btts"]
    btts_line = f"Ambos anotan (BTTS):  Si {_pct(btts['yes'])}   No {_pct(btts['no'])}"
    draw.text((MARGIN, y), btts_line, font=f, fill=TEXT)
    y += 44

    y = _section_title(draw, y, "Over / Under goles")
    ou = model["over_under"]
    f_ou = font(18)
    col_w = (WIDTH - 2 * MARGIN) / len(ou)
    for i, (line, probs) in enumerate(sorted(ou.items())):
        cx = MARGIN + col_w * i + col_w / 2
        _center_text(draw, cx, y, f"{line}", f_ou, SUBTEXT)
        _center_text(draw, cx, y + 24, f"O {_pct(probs['over'])}", f_ou, GREEN)
        _center_text(draw, cx, y + 46, f"U {_pct(probs['under'])}", f_ou, RED)
    y += 84

    top_scores = model.get("top_scorelines", [])
    if top_scores:
        y = _section_title(draw, y, "Marcadores mas probables")
        f_score = font(20, bold=True)
        col_w = (WIDTH - 2 * MARGIN) / len(top_scores)
        for i, (hx, ay, p) in enumerate(top_scores):
            cx = MARGIN + col_w * i + col_w / 2
            _center_text(draw, cx, y, f"{hx}-{ay}", f_score, TEXT)
            _center_text(draw, cx, y + 26, _pct(p), f_score, SUBTEXT)
        y += 60

    # Odds
    odds = payload.get("odds")
    if odds:
        y = _section_title(draw, y, f"Cuotas ({odds.get('bookmaker', 'mercado')}) vs modelo")
        mo = odds.get("match_odds", {})
        if mo.get("home") is not None:
            y = _odds_vs_model_row(draw, y, "Local (1)", result["home"], mo.get("home"), payload.get("edges", {}).get("home"))
        if mo.get("draw") is not None:
            y = _odds_vs_model_row(draw, y, "Empate (X)", result["draw"], mo.get("draw"), payload.get("edges", {}).get("draw"))
        if mo.get("away") is not None:
            y = _odds_vs_model_row(draw, y, "Visita (2)", result["away"], mo.get("away"), payload.get("edges", {}).get("away"))
        b = odds.get("btts", {})
        if b.get("yes") is not None:
            y = _odds_vs_model_row(draw, y, "BTTS Si", btts["yes"], b.get("yes"), payload.get("edges", {}).get("btts_yes"))
        if b.get("no") is not None:
            y = _odds_vs_model_row(draw, y, "BTTS No", btts["no"], b.get("no"), payload.get("edges", {}).get("btts_no"))
        y += 20
    else:
        y = _section_title(draw, y, "Cuotas")
        f_note = font(18)
        draw.text((MARGIN, y), "No disponibles para este partido.", font=f_note, fill=SUBTEXT)
        y += 40

    # Footer
    y += 20
    f_foot = font(15)
    disclaimer = (
        "Ficha generada automaticamente. Probabilidades del modelo son estimaciones "
        "informativas, no garantia de resultado ni recomendacion de apuesta."
    )
    _center_text(draw, WIDTH / 2, y, disclaimer, f_foot, SUBTEXT)
    y += 40

    return img.crop((0, 0, WIDTH, min(canvas_h, y)))


def generate_ficha(payload: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _render_ficha(payload).save(output_path, "PNG")
    return output_path


def generate_ficha_bytes(payload: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    _render_ficha(payload).save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------------ #
# Form / rating profile ficha (attack & defense 0-100 bars)
# ------------------------------------------------------------------------ #
def _rating_row(draw, y, label, value, color) -> int:
    f = font(20)
    fb = font(22, bold=True)
    draw.text((MARGIN, y), label, font=f, fill=SUBTEXT)
    bar_x = MARGIN + 160
    bar_w = WIDTH - 2 * MARGIN - 160 - 70
    _bar(draw, bar_x, y - 2, bar_w, 26, value / 100, color)
    val_text = f"{value:.0f}"
    draw.text((bar_x + bar_w + 16, y - 4), val_text, font=fb, fill=color)
    return y + 44


def _render_form_ficha(payload: dict[str, Any]) -> Image.Image:
    canvas_h = 700
    img = Image.new("RGB", (WIDTH, canvas_h), BG)
    draw = ImageDraw.Draw(img)

    home = payload["home_team"]
    away = payload["away_team"]
    n = payload.get("form_n", 5)

    y = MARGIN
    f_title = font(28, bold=True)
    _center_text(draw, WIDTH / 2, y, payload.get("competition_name", "").upper(), f_title, GOLD)
    y += 40
    f_sub = font(18)
    _center_text(draw, WIDTH / 2, y, f"Perfil de ataque y defensa (ultimos {n} partidos)", f_sub, SUBTEXT)
    y += 56

    for team, rating_key, color in (("home_team", "home_rating", ACCENT_HOME), ("away_team", "away_rating", ACCENT_AWAY)):
        team_info = payload[team]
        rating = payload[rating_key]
        f_name = font(26, bold=True)
        draw.text((MARGIN, y), team_info["name"], font=f_name, fill=color)
        f_level = font(18)
        level_text = f"nivel: {rating['level']}"
        w = _text_w(draw, level_text, f_level)
        draw.text((WIDTH - MARGIN - w, y + 4), level_text, font=f_level, fill=SUBTEXT)
        y += 46
        y = _rating_row(draw, y, "Ataque", rating["attack"], color)
        y = _rating_row(draw, y, "Defensa", rating["defense"], color)
        y += 30

    y += 10
    f_foot = font(15)
    disclaimer = (
        "Rating 0-100 basado en xG, tiros y tiros a puerta (a favor y en contra). "
        "Informativo, no garantiza resultado."
    )
    _center_text(draw, WIDTH / 2, y, disclaimer, f_foot, SUBTEXT)
    y += 40

    return img.crop((0, 0, WIDTH, min(canvas_h, y)))


def generate_form_ficha(payload: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _render_form_ficha(payload).save(output_path, "PNG")
    return output_path


def generate_form_ficha_bytes(payload: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    _render_form_ficha(payload).save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------------ #
# Match-by-match ficha (last N games, shots / on target / corners per side)
# ------------------------------------------------------------------------ #
def _match_card(draw, x, y, w, h, record: dict[str, Any], team_color) -> None:
    _rounded_rect(draw, (x, y, x + w, y + h), 14, CARD_BG)
    pad = 20
    cy = y + pad

    prefix = "vs" if record["is_home"] else "@"
    header = f"{prefix} {record['opponent_name']}"
    f_head = font(19, bold=True)
    _center_text(draw, x + w / 2, cy, header, f_head, TEXT)
    cy += 30

    team_goals, opp_goals = record["team_goals"], record["opp_goals"]
    score_text = f"{team_goals}-{opp_goals}"
    f_score = font(26, bold=True)
    if team_goals > opp_goals:
        score_color = GREEN
    elif team_goals < opp_goals:
        score_color = RED
    else:
        score_color = GRAY
    _center_text(draw, x + w / 2, cy, score_text, f_score, score_color)
    cy += 48

    rows = [
        ("Tiros", record["team_shots"], record["opp_shots"]),
        ("A puerta", record["team_sot"], record["opp_sot"]),
        ("Corners", record["team_corners"], record["opp_corners"]),
    ]
    f_val = font(20, bold=True)
    f_lbl = font(15)
    for label, team_val, opp_val in rows:
        team_text = "-" if team_val is None else f"{team_val:.0f}"
        opp_text = "-" if opp_val is None else f"{opp_val:.0f}"
        draw.text((x + pad, cy), team_text, font=f_val, fill=team_color)
        _center_text(draw, x + w / 2, cy + 3, label, f_lbl, SUBTEXT)
        opp_w = _text_w(draw, opp_text, f_val)
        draw.text((x + w - pad - opp_w, cy), opp_text, font=f_val, fill=TEXT)
        cy += 34


def _render_match_by_match_ficha(payload: dict[str, Any]) -> Image.Image:
    home = payload["home_team"]
    away = payload["away_team"]
    home_records = payload["home_recent_matches"]
    away_records = payload["away_recent_matches"]
    n_rows = max(len(home_records), len(away_records), 1)

    card_h = 190
    card_gap_y = 20
    header_h = 170
    canvas_h = header_h + n_rows * (card_h + card_gap_y) + 80
    img = Image.new("RGB", (WIDTH, canvas_h), BG)
    draw = ImageDraw.Draw(img)

    y = MARGIN
    f_title = font(28, bold=True)
    _center_text(draw, WIDTH / 2, y, payload.get("competition_name", "").upper(), f_title, GOLD)
    y += 40
    f_sub = font(18)
    _center_text(draw, WIDTH / 2, y, "Resumen partido a partido (forma reciente)", f_sub, SUBTEXT)
    y += 40

    gap_x = 24
    col_w = (WIDTH - 2 * MARGIN - gap_x) / 2
    col_x_home = MARGIN
    col_x_away = MARGIN + col_w + gap_x

    f_team = font(24, bold=True)
    _center_text(draw, col_x_home + col_w / 2, y, home["name"], f_team, ACCENT_HOME)
    _center_text(draw, col_x_away + col_w / 2, y, away["name"], f_team, ACCENT_AWAY)
    y += 44

    cards_top = y
    for i in range(n_rows):
        cy = cards_top + i * (card_h + card_gap_y)
        if i < len(home_records):
            _match_card(draw, col_x_home, cy, col_w, card_h, home_records[i], ACCENT_HOME)
        if i < len(away_records):
            _match_card(draw, col_x_away, cy, col_w, card_h, away_records[i], ACCENT_AWAY)
    y = cards_top + n_rows * (card_h + card_gap_y) + 10

    f_foot = font(15)
    _center_text(draw, WIDTH / 2, y, "Numeros de cada equipo y su rival en el mismo partido.", f_foot, SUBTEXT)
    y += 30

    return img.crop((0, 0, WIDTH, min(canvas_h, y)))


def generate_match_by_match_ficha(payload: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _render_match_by_match_ficha(payload).save(output_path, "PNG")
    return output_path


def generate_match_by_match_ficha_bytes(payload: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    _render_match_by_match_ficha(payload).save(buf, "PNG")
    return buf.getvalue()
