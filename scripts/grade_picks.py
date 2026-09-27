#!/usr/bin/env python3
"""Califica picks de semanas pasadas con marcadores finales (ESPN scoreboard público).

Marcadores: site.api.espn.com (no verificado como estable; si falla deja result=null y avisa).
Califica moneyline, spread y total. Props de jugador quedan en null salvo que el pick traiga
"result_manual". Actualiza data/picks/{season}-W{nn}.json y el récord por canal.

Uso:  python scripts/grade_picks.py [2026-W03] [--dry]
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICKS = ROOT / "data" / "picks"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={season}&seasontype=2&week={week}"


def fetch_scores(season, week):
    import requests
    r = requests.get(ESPN.format(season=season, week=week), timeout=30)
    r.raise_for_status()
    games = []
    for ev in r.json().get("events", []):
        comp = ev["competitions"][0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        teams = {}
        for c in comp["competitors"]:
            t = c["team"]
            teams[c["homeAway"]] = {"abbr": t.get("abbreviation", ""), "name": t.get("name", ""), "display": t.get("displayName", ""), "score": float(c.get("score") or 0)}
        games.append({"id": ev["id"], "home": teams["home"], "away": teams["away"], "label": f"{teams['away']['abbr']} @ {teams['home']['abbr']}"})
    return games


def team_in(text, team):
    t = (text or "").lower()
    return any(k and k.lower() in t for k in (team["abbr"], team["name"], team["display"]))


def find_game(games, pick):
    g = (pick.get("game") or "").upper().replace("VS", "@")
    for game in games:
        if game["label"].upper() == g.strip():
            return game
    for game in games:  # por nombre de equipo en el texto
        if team_in(pick.get("game", "") + " " + pick.get("selection", ""), game["home"]) and team_in(pick.get("game", "") + " " + pick.get("selection", ""), game["away"]):
            return game
    return None


def grade(pick, game):
    if pick.get("result_manual"):
        return pick["result_manual"], "manual"
    if not game:
        return None, "partido no encontrado en ESPN"
    sel, market = pick.get("selection", ""), pick.get("market")
    h, a = game["home"], game["away"]
    if market == "moneyline":
        team = h if team_in(sel, h) and not team_in(sel, a) else a if team_in(sel, a) else None
        if not team:
            return None, "equipo no identificado"
        other = a if team is h else h
        if pick.get("category") == "ml_1h":
            return None, "1a mitad requiere marcador parcial (no disponible)"
        return ("win" if team["score"] > other["score"] else "loss" if team["score"] < other["score"] else "push"), "auto"
    if market == "spread":
        team = h if team_in(sel, h) and not team_in(sel, a) else a if team_in(sel, a) else None
        line = pick.get("line")
        if line is None:
            m = re.search(r"([+-]\d+(?:\.\d+)?)", sel)
            line = float(m.group(1)) if m else None
        if not team or line is None:
            return None, "spread sin equipo o línea"
        other = a if team is h else h
        diff = team["score"] + float(line) - other["score"]
        return ("win" if diff > 0 else "loss" if diff < 0 else "push"), "auto"
    if market == "total":
        line = pick.get("line")
        if line is None:
            m = re.search(r"(\d+(?:\.\d+)?)", sel)
            line = float(m.group(1)) if m else None
        if line is None:
            return None, "total sin línea"
        tot = h["score"] + a["score"]
        over = "over" in sel.lower() or "más" in sel.lower() or "mas de" in sel.lower()
        if tot == float(line):
            return "push", "auto"
        return ("win" if (tot > float(line)) == over else "loss"), "auto"
    return None, f"mercado {market} no se califica automáticamente"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    files = [PICKS / f"{args[0]}.json"] if args else sorted(PICKS.glob("*-W*.json"))
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        pend = [p for p in d.get("picks", []) if p.get("result") is None]
        if not pend:
            print(f"{f.name}: nada pendiente")
            continue
        try:
            games = fetch_scores(d["season"], d["week"])
        except Exception as e:  # noqa: BLE001
            print(f"{f.name}: ESPN falló ({type(e).__name__}: {e}). Se dejan result=null.")
            continue
        n_ok = 0
        for p in pend:
            res, how = grade(p, find_game(games, p))
            p["result"] = res
            p["graded_by"] = how
            n_ok += res is not None
        rec = {}
        for p in d.get("picks", []):
            if p.get("result") in ("win", "loss", "push"):
                r = rec.setdefault(p.get("channel", "?"), {"win": 0, "loss": 0, "push": 0, "units": 0.0})
                r[p["result"]] += 1
                if p["result"] == "win" and p.get("odds_decimal"):
                    r["units"] = round(r["units"] + float(p["odds_decimal"]) - 1, 2)
                elif p["result"] == "loss":
                    r["units"] = round(r["units"] - 1, 2)
        d["record"] = rec
        d["graded_at"] = date.today().isoformat()
        if not dry:
            f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{f.name}: {n_ok}/{len(pend)} calificados | récord {rec}")


if __name__ == "__main__":
    main()
