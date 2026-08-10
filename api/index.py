"""Flask web app exposing the pre-match ficha generator as an HTTP form.

Deployed on Vercel via the @vercel/python builder (see vercel.json). Locally
it can also be run directly with `python api/index.py` for testing.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, request
from markupsafe import escape

from api_client import StatsAPIClient, StatsAPIError
from ficha_generator import (
    generate_ficha_bytes,
    generate_form_ficha_bytes,
    generate_h2h_ficha_bytes,
    generate_match_by_match_ficha_bytes,
    generate_recent_form_summary_ficha_bytes,
)
from prematch_analysis import build_payload

app = Flask(__name__)

PAGE_HEAD = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ficha pre-partido - TheStatsAPI</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; background:#10141f; color:#ebedf2;
         max-width:720px; margin:0 auto; padding:32px 16px; }
  h1 { font-size:22px; margin-bottom:4px; }
  p.sub { color:#96a0b0; margin-top:0; }
  form { background:#1a1f30; padding:20px; border-radius:12px; display:grid; gap:12px; }
  label { font-size:14px; color:#96a0b0; }
  input { width:100%; box-sizing:border-box; padding:10px; border-radius:8px; border:1px solid #333c54;
          background:#0f1320; color:#ebedf2; font-size:15px; }
  button { padding:12px; border:none; border-radius:8px; background:#4da3ff; color:#0f1320;
           font-weight:600; font-size:15px; cursor:pointer; }
  button:hover { background:#6cb5ff; }
  .error { background:#3a1f22; border:1px solid #ff8a8a; color:#ffb3b3; padding:12px; border-radius:8px; }
  .row { display:flex; gap:12px; }
  .row > div { flex:1; }
  img { max-width:100%; border-radius:8px; margin-top:20px; }
  a.back { color:#4da3ff; display:inline-block; margin-top:16px; }
</style>
</head>
<body>
<h1>Ficha pre-partido</h1>
<p class="sub">Analisis automatico (Poisson + Dixon-Coles) usando TheStatsAPI</p>
"""

PAGE_TAIL = "</body></html>"

FORM_HTML = """
<form method="get" action="/analyze">
  <div class="row">
    <div>
      <label for="home">Equipo local</label>
      <input id="home" name="home" placeholder="Real Madrid" required>
    </div>
    <div>
      <label for="away">Equipo visitante</label>
      <input id="away" name="away" placeholder="Barcelona" required>
    </div>
  </div>
  <div>
    <label for="date">Fecha aproximada (opcional)</label>
    <input id="date" name="date" placeholder="2026-08-15">
  </div>
  <button type="submit">Generar ficha</button>
</form>
"""


def render_page(body: str) -> str:
    return PAGE_HEAD + body + PAGE_TAIL


@app.route("/", methods=["GET"])
def index():
    return render_page(FORM_HTML)


@app.route("/analyze", methods=["GET"])
def analyze():
    home = (request.args.get("home") or "").strip()
    away = (request.args.get("away") or "").strip()
    match_id = (request.args.get("match_id") or "").strip() or None
    date = (request.args.get("date") or "").strip() or None

    if not match_id and (not home or not away):
        error = "<p class='error'>Indica equipo local y visitante, o un match_id.</p>"
        return render_page(error + FORM_HTML), 400

    try:
        client = StatsAPIClient()
    except StatsAPIError as exc:
        error = f"<p class='error'>{escape(str(exc))}</p>"
        return render_page(error + FORM_HTML), 500

    try:
        payload = build_payload(client, home=home or None, away=away or None, match_id=match_id, date=date)
    except ValueError as exc:
        error = f"<p class='error'>{escape(str(exc))}</p>"
        return render_page(error + FORM_HTML), 404

    def img_tag(png_bytes: bytes, alt: str) -> str:
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return f"<img src='data:image/png;base64,{b64}' alt='{alt}'>"

    result = payload["model"]["result"]
    btts = payload["model"]["btts"]
    summary = (
        f"<p>1X2 &rarr; Local {result['home']*100:.1f}% &middot; "
        f"Empate {result['draw']*100:.1f}% &middot; Visita {result['away']*100:.1f}%<br>"
        f"BTTS &rarr; Si {btts['yes']*100:.1f}% &middot; No {btts['no']*100:.1f}%</p>"
    )
    body = (
        f"{summary}"
        f"{img_tag(generate_ficha_bytes(payload), 'Ficha pre-partido')}"
        f"{img_tag(generate_recent_form_summary_ficha_bytes(payload), 'Forma reciente y recomendacion')}"
        f"{img_tag(generate_form_ficha_bytes(payload), 'Perfil de ataque y defensa')}"
        f"{img_tag(generate_match_by_match_ficha_bytes(payload), 'Resumen partido a partido')}"
        f"{img_tag(generate_h2h_ficha_bytes(payload), 'Enfrentamientos directos')}"
        f"<div><a class='back' href='/'>&larr; Nuevo analisis</a></div>"
    )
    return render_page(body)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
