"""Renders the pre-match analysis ficha as a PNG using Pillow.

No external assets required — team "logos" are drawn as colored initials
circles since the API does not expose crest URLs.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from models import project_combined_stat

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
    max_src_w = WIDTH - 2 * MARGIN
    src_lines = _wrap_text(draw, src_note, f_small, max_src_w)
    line_y = y + 6
    for line in src_lines:
        _center_text(draw, WIDTH / 2, line_y, line, f_small, SUBTEXT)
        line_y += 20
    y = line_y + 14

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
        cols_per_row = 5
        row_h = 56
        col_w = (WIDTH - 2 * MARGIN) / min(len(top_scores), cols_per_row)
        for i, (hx, ay, p) in enumerate(top_scores):
            row, col = divmod(i, cols_per_row)
            cx = MARGIN + col_w * col + col_w / 2
            row_y = y + row * row_h
            _center_text(draw, cx, row_y, f"{hx}-{ay}", f_score, TEXT)
            _center_text(draw, cx, row_y + 26, _pct(p), f_score, SUBTEXT)
        n_rows = -(-len(top_scores) // cols_per_row)  # ceil division
        y += n_rows * row_h + 4

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

    if record.get("date"):
        f_date = font(14)
        _center_text(draw, x + w / 2, cy, record["date"], f_date, SUBTEXT)
        cy += 20

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

    card_h = 210
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


# ------------------------------------------------------------------------ #
# Head-to-head ficha (last N direct meetings, any competition)
# ------------------------------------------------------------------------ #
def _h2h_row(draw, y_top: int, record: dict[str, Any], current_home_id: str) -> None:
    cy = y_top + 14
    f_date = font(15)
    comp = record.get("competition_name") or ""
    header = f"{record['date']}  ·  {comp}" if comp else record["date"]
    _center_text(draw, WIDTH / 2, cy, header, f_date, SUBTEXT)
    cy += 24

    home_color = ACCENT_HOME if record["home_id"] == current_home_id else ACCENT_AWAY
    away_color = ACCENT_AWAY if record["home_id"] == current_home_id else ACCENT_HOME
    home_goals, away_goals = record["home_goals"], record["away_goals"]
    if home_goals > away_goals:
        score_color = home_color
    elif away_goals > home_goals:
        score_color = away_color
    else:
        score_color = GRAY

    f_name = font(19, bold=True)
    f_score = font(21, bold=True)
    home_text, away_text = record["home_name"], record["away_name"]
    score_text = f"{home_goals} - {away_goals}"
    hw = _text_w(draw, home_text, f_name)
    sw = _text_w(draw, score_text, f_score)
    aw = _text_w(draw, away_text, f_name)
    gap = 18
    start_x = WIDTH / 2 - (hw + gap + sw + gap + aw) / 2
    draw.text((start_x, cy), home_text, font=f_name, fill=home_color)
    draw.text((start_x + hw + gap, cy - 1), score_text, font=f_score, fill=score_color)
    draw.text((start_x + hw + gap + sw + gap, cy), away_text, font=f_name, fill=away_color)


def _render_h2h_ficha(payload: dict[str, Any]) -> Image.Image:
    home = payload["home_team"]
    records = payload.get("head_to_head", [])
    n = payload.get("h2h_n", 5)

    row_h = 80
    header_h = 130
    canvas_h = header_h + max(len(records), 1) * row_h + 70
    img = Image.new("RGB", (WIDTH, canvas_h), BG)
    draw = ImageDraw.Draw(img)

    y = MARGIN
    f_title = font(28, bold=True)
    _center_text(draw, WIDTH / 2, y, payload.get("competition_name", "").upper(), f_title, GOLD)
    y += 40
    f_sub = font(18)
    _center_text(draw, WIDTH / 2, y, f"Ultimos {n} enfrentamientos directos", f_sub, SUBTEXT)
    y += 40

    card_top = y
    card_h_total = max(len(records), 1) * row_h
    _rounded_rect(draw, (MARGIN, card_top, WIDTH - MARGIN, card_top + card_h_total), 14, CARD_BG)

    if not records:
        f_empty = font(20)
        _center_text(draw, WIDTH / 2, card_top + row_h / 2 - 10, "Sin enfrentamientos previos registrados.", f_empty, SUBTEXT)
    else:
        for i, record in enumerate(records):
            row_top = card_top + i * row_h
            _h2h_row(draw, row_top, record, home["id"])
            if i < len(records) - 1:
                line_y = row_top + row_h
                draw.line((MARGIN + 24, line_y, WIDTH - MARGIN - 24, line_y), fill=(52, 58, 79), width=1)

    y = card_top + card_h_total + 30
    f_foot = font(15)
    _center_text(draw, WIDTH / 2, y, "Resultados historicos entre ambos equipos, en cualquier competicion.", f_foot, SUBTEXT)
    y += 30

    return img.crop((0, 0, WIDTH, min(canvas_h, y)))


def generate_h2h_ficha(payload: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _render_h2h_ficha(payload).save(output_path, "PNG")
    return output_path


def generate_h2h_ficha_bytes(payload: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    _render_h2h_ficha(payload).save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------------ #
# Recent-form summary ficha (form/goals, per-match averages, combined
# match-stat projection, 1X2 + double chance, betting-angle recommendation)
# ------------------------------------------------------------------------ #
def _pct1(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt1(v: float | None) -> str:
    return "N/D" if v is None else f"{v:.1f}"


def _signed_int(n: float) -> str:
    n = round(n)
    return f"+{n}" if n > 0 else f"{n}"


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or _text_w(draw, candidate, f) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_paragraph(draw, x, y, text, f, fill, max_width, line_height) -> int:
    for line in _wrap_text(draw, text, f, max_width):
        draw.text((x, y), line, font=f, fill=fill)
        y += line_height
    return y


FORM_BOX_H = 210
AVG_BOX_H = 210


def _recent_form_box(draw, x, y, w, summary: dict[str, Any], accent_color) -> None:
    _rounded_rect(draw, (x, y, x + w, y + FORM_BOX_H), 14, CARD_BG)
    pad = 20
    cy = y + pad

    n = summary["games_used"]
    f_lbl = font(15, bold=True)
    title = f"FORMA RECIENTE (ULTIMOS {n})" if n else "FORMA RECIENTE"
    _center_text(draw, x + w / 2, cy, title, f_lbl, SUBTEXT)
    cy += 30

    max_pts = n * 3
    f_big = font(30, bold=True)
    _center_text(draw, x + w / 2, cy, f"{summary['points']} / {max_pts} pts", f_big, accent_color)
    cy += 48

    goal_diff = summary["goals_for"] - summary["goals_against"]
    diff_color = GREEN if goal_diff > 0 else (RED if goal_diff < 0 else GRAY)
    rows = [
        ("Goles a favor", f"{summary['goals_for']:.0f}", TEXT),
        ("Goles en contra", f"{summary['goals_against']:.0f}", TEXT),
        ("Diferencia de gol", _signed_int(goal_diff), diff_color),
    ]
    f_row_lbl = font(16)
    f_row_val = font(18, bold=True)
    for label, val, color in rows:
        draw.text((x + pad, cy), label, font=f_row_lbl, fill=SUBTEXT)
        vw = _text_w(draw, val, f_row_val)
        draw.text((x + w - pad - vw, cy - 1), val, font=f_row_val, fill=color)
        cy += 26


def _recent_averages_box(draw, x, y, w, summary: dict[str, Any], xg_estimate: float) -> None:
    _rounded_rect(draw, (x, y, x + w, y + AVG_BOX_H), 14, CARD_BG)
    pad = 20
    cy = y + pad

    f_lbl = font(15, bold=True)
    _center_text(draw, x + w / 2, cy, "PROMEDIO POR PARTIDO", f_lbl, SUBTEXT)
    cy += 30

    rows = [
        ("Tiros (favor/contra)", f"{_fmt1(summary['avg_shots_for'])} / {_fmt1(summary['avg_shots_against'])}"),
        ("A puerta (favor/contra)", f"{_fmt1(summary['avg_sot_for'])} / {_fmt1(summary['avg_sot_against'])}"),
        ("Corners (favor/contra)", f"{_fmt1(summary['avg_corners_for'])} / {_fmt1(summary['avg_corners_against'])}"),
    ]
    f_row_lbl = font(16)
    f_row_val = font(17, bold=True)
    for label, val in rows:
        draw.text((x + pad, cy), label, font=f_row_lbl, fill=SUBTEXT)
        vw = _text_w(draw, val, f_row_val)
        draw.text((x + w - pad - vw, cy - 1), val, font=f_row_val, fill=TEXT)
        cy += 26

    cy += 8
    draw.line((x + pad, cy, x + w - pad, cy), fill=(52, 58, 79), width=1)
    cy += 16
    f_xg_lbl = font(14)
    _center_text(draw, x + w / 2, cy, "XG ESTIMADO", f_xg_lbl, SUBTEXT)
    cy += 20
    f_xg_val = font(24, bold=True)
    _center_text(draw, x + w / 2, cy, f"{xg_estimate:.1f}", f_xg_val, TEXT)


def _combined_estimate_box(draw, y, home_summary: dict[str, Any], away_summary: dict[str, Any]) -> int:
    rows_def = [
        (
            "Tiros",
            project_combined_stat(
                home_summary["avg_shots_for"],
                away_summary["avg_shots_against"],
                away_summary["avg_shots_for"],
                home_summary["avg_shots_against"],
            ),
        ),
        (
            "A puerta",
            project_combined_stat(
                home_summary["avg_sot_for"],
                away_summary["avg_sot_against"],
                away_summary["avg_sot_for"],
                home_summary["avg_sot_against"],
            ),
        ),
        (
            "Corners",
            project_combined_stat(
                home_summary["avg_corners_for"],
                away_summary["avg_corners_against"],
                away_summary["avg_corners_for"],
                home_summary["avg_corners_against"],
            ),
        ),
    ]

    pad = 20
    row_h = 32
    box_h = 32 + len(rows_def) * row_h + 16
    box_x0, box_x1 = MARGIN, WIDTH - MARGIN
    _rounded_rect(draw, (box_x0, y, box_x1, y + box_h), 14, CARD_BG)

    cy = y + 18
    f_lbl = font(15, bold=True)
    _center_text(draw, WIDTH / 2, cy, "ESTIMADO DEL PARTIDO (TOTAL COMBINADO)", f_lbl, SUBTEXT)
    cy += 32

    f_row_lbl = font(17, bold=True)
    f_row_val = font(18, bold=True)
    label_x = box_x0 + pad
    home_x = box_x0 + 190
    plus_x = box_x0 + 290
    away_x = box_x0 + 320
    total_right = box_x1 - pad

    for label, (home_v, away_v, total_v) in rows_def:
        draw.text((label_x, cy), label, font=f_row_lbl, fill=TEXT)
        draw.text((home_x, cy), _fmt1(home_v), font=f_row_val, fill=ACCENT_HOME)
        draw.text((plus_x, cy), "+", font=f_row_lbl, fill=SUBTEXT)
        draw.text((away_x, cy), _fmt1(away_v), font=f_row_val, fill=ACCENT_AWAY)
        total_text = f"Total: {_fmt1(total_v)}"
        tw = _text_w(draw, total_text, f_row_lbl)
        draw.text((total_right - tw, cy), total_text, font=f_row_lbl, fill=SUBTEXT)
        cy += row_h

    return y + box_h


def _probability_block(draw, y, home_name: str, away_name: str, payload: dict[str, Any]) -> int:
    result = payload["model"]["result"]
    dc = payload["model"]["double_chance"]

    pad = 20
    box_x0, box_x1 = MARGIN, WIDTH - MARGIN
    bar_w = box_x1 - box_x0 - 2 * pad
    box_h = 32 + 16 + 30 + 16 + 24 + 16 + 24 + 24 + 16
    _rounded_rect(draw, (box_x0, y, box_x1, y + box_h), 14, CARD_BG)

    cy = y + 18
    f_lbl = font(15, bold=True)
    _center_text(draw, WIDTH / 2, cy, "PROBABILIDADES DE RESULTADO (MODELO POISSON, SEGUN XG)", f_lbl, SUBTEXT)
    cy += 34

    bar_x = box_x0 + pad
    bar_h = 14
    home_p, draw_p, away_p = result["home"], result["draw"], result["away"]
    seg_home = int(bar_w * home_p)
    seg_draw = int(bar_w * draw_p)
    _rounded_rect(draw, (bar_x, cy, bar_x + bar_w, cy + bar_h), bar_h // 2, (52, 58, 79))
    draw.rectangle((bar_x, cy, bar_x + seg_home, cy + bar_h), fill=ACCENT_HOME)
    draw.rectangle((bar_x + seg_home, cy, bar_x + seg_home + seg_draw, cy + bar_h), fill=GRAY)
    draw.rectangle((bar_x + seg_home + seg_draw, cy, bar_x + bar_w, cy + bar_h), fill=ACCENT_AWAY)
    cy += bar_h + 14

    f_res = font(17, bold=True)
    draw.text((bar_x, cy), f"1: {_pct1(home_p)}", font=f_res, fill=ACCENT_HOME)
    _center_text(draw, WIDTH / 2, cy, f"X: {_pct1(draw_p)}", f_res, TEXT)
    away_text = f"2: {_pct1(away_p)}"
    aw = _text_w(draw, away_text, f_res)
    draw.text((bar_x + bar_w - aw, cy), away_text, font=f_res, fill=ACCENT_AWAY)
    cy += 34

    f_dc_lbl = font(16)
    f_dc_val = font(16, bold=True)
    dc_rows = [
        (f"Doble oportunidad X2 (empate o {away_name}):", dc["draw_or_away"]),
        (f"Doble oportunidad 1X ({home_name} o empate):", dc["home_or_draw"]),
    ]
    for label, value in dc_rows:
        draw.text((bar_x, cy), label, font=f_dc_lbl, fill=SUBTEXT)
        val_text = _pct1(value)
        vw = _text_w(draw, val_text, f_dc_val)
        draw.text((bar_x + bar_w - vw, cy), val_text, font=f_dc_val, fill=TEXT)
        cy += 24

    return y + box_h


def _recommendation_box(draw, y, recommendation: dict[str, Any]) -> int:
    pad = 22
    border_w = 6
    box_x0, box_x1 = MARGIN, WIDTH - MARGIN
    max_text_w = box_x1 - box_x0 - 2 * pad - border_w

    f_kicker = font(15, bold=True)
    f_market = font(22, bold=True)
    f_body = font(16)
    line_h = 24

    body_lines = _wrap_text(draw, recommendation["rationale"], f_body, max_text_w)
    box_h = pad + 20 + 10 + 30 + 12 + len(body_lines) * line_h + pad

    _rounded_rect(draw, (box_x0, y, box_x1, y + box_h), 14, (18, 38, 30))
    draw.rectangle((box_x0, y, box_x0 + border_w, y + box_h), fill=GREEN)

    cy = y + pad
    text_x = box_x0 + border_w + pad
    draw.text((text_x, cy), "RECOMENDACION DE APUESTA", font=f_kicker, fill=GREEN)
    cy += 30
    draw.text((text_x, cy), recommendation["market"], font=f_market, fill=TEXT)
    cy += 42
    _draw_paragraph(draw, text_x, cy, recommendation["rationale"], f_body, SUBTEXT, max_text_w, line_h)

    return y + box_h


def _render_recent_form_summary_ficha(payload: dict[str, Any]) -> Image.Image:
    home = payload["home_team"]
    away = payload["away_team"]
    home_summary = payload["home_recent_summary"]
    away_summary = payload["away_recent_summary"]
    recommendation = payload["recommendation"]

    canvas_h = 1700
    img = Image.new("RGB", (WIDTH, canvas_h), BG)
    draw = ImageDraw.Draw(img)

    y = MARGIN
    f_title = font(26, bold=True)
    _center_text(draw, WIDTH / 2, y, payload.get("competition_name", "").upper(), f_title, GOLD)
    y += 36
    f_sub = font(17)
    _center_text(draw, WIDTH / 2, y, "Proyeccion del partido", f_sub, SUBTEXT)
    y += 44

    gap_x = 24
    col_w = (WIDTH - 2 * MARGIN - gap_x) / 2
    col_x_home = MARGIN
    col_x_away = MARGIN + col_w + gap_x

    f_team = font(23, bold=True)
    _center_text(draw, col_x_home + col_w / 2, y, home["name"], f_team, ACCENT_HOME)
    _center_text(draw, col_x_away + col_w / 2, y, away["name"], f_team, ACCENT_AWAY)
    y += 40

    _recent_form_box(draw, col_x_home, y, col_w, home_summary, ACCENT_HOME)
    _recent_form_box(draw, col_x_away, y, col_w, away_summary, ACCENT_AWAY)
    y += FORM_BOX_H + 16

    _recent_averages_box(draw, col_x_home, y, col_w, home_summary, payload.get("lambda_home", 0.0))
    _recent_averages_box(draw, col_x_away, y, col_w, away_summary, payload.get("lambda_away", 0.0))
    y += AVG_BOX_H + 16

    y = _combined_estimate_box(draw, y, home_summary, away_summary)
    y += 16

    y = _probability_block(draw, y, home["name"], away["name"], payload)
    y += 16

    y = _recommendation_box(draw, y, recommendation)
    y += 20

    f_foot = font(14)
    n = min(home_summary["games_used"], away_summary["games_used"])
    disclaimer = (
        f"Proyeccion basada en estadisticas de los ultimos {n or 'N'} partidos de cada equipo. "
        "Estimacion estadistica, no una garantia de resultado."
    )
    y = _draw_paragraph(draw, MARGIN, y, disclaimer, f_foot, SUBTEXT, WIDTH - 2 * MARGIN, 20)
    y += 20

    return img.crop((0, 0, WIDTH, min(canvas_h, y)))


def generate_recent_form_summary_ficha(payload: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _render_recent_form_summary_ficha(payload).save(output_path, "PNG")
    return output_path


def generate_recent_form_summary_ficha_bytes(payload: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    _render_recent_form_summary_ficha(payload).save(buf, "PNG")
    return buf.getvalue()
