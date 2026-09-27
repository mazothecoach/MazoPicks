#!/usr/bin/env python3
"""Métricas de mis apuestas (data/my_bets.json) -> data/my_bets_analysis.json.

Todas las métricas llevan n visible y advertencia si n < 10. Incluye la sección
"Qué sí / Qué no" con reglas derivadas de los datos y su n.

Uso:  python scripts/analyze_my_bets.py
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "my_bets.json"
OUT = ROOT / "data" / "my_bets_analysis.json"

SETTLED = {"won", "lost", "cashed_out", "void"}
CATEGORY_LABELS = {
    "ml": "Moneyline", "ml_1h": "Moneyline 1a mitad", "spread": "Spread", "total": "Total (O/U)",
    "td_scorer": "Anotador de TD", "pass_yds": "Yardas por pase", "pass_comp": "Pases completados",
    "rush_yds": "Yardas por tierra", "rec_yds": "Yardas por recepción", "receptions": "Recepciones", "other": "Otro",
}


def r(x, d=3):
    return None if x is None else round(x, d)


def cost(t):
    return 0.0 if t.get("free_bet") else float(t.get("stake_mxn") or 0)


def group_stats(tickets):
    n = len(tickets)
    inv = sum(cost(t) for t in tickets)
    col = sum(float(t.get("payout_mxn") or 0) for t in tickets)
    won = sum(1 for t in tickets if t["status"] == "won" or (t["status"] == "cashed_out" and float(t.get("payout_mxn") or 0) > cost(t)))
    return {
        "n": n, "invertido_mxn": r(inv, 2), "cobrado_mxn": r(col, 2), "profit_mxn": r(col - inv, 2),
        "roi": r((col - inv) / inv) if inv else None, "ganados": won, "hit_rate": r(won / n) if n else None,
        "muestra_chica": n < 10,
    }


def legs_bucket(n):
    return "1" if n == 1 else "2" if n == 2 else "3" if n == 3 else "4+"


def hour_bucket(placed_at):
    try:
        h = datetime.fromisoformat(placed_at).hour
    except Exception:  # noqa: BLE001
        return "desconocido"
    if 0 <= h < 6:
        return "madrugada (00-06)"
    if h < 12:
        return "mañana (06-12)"
    if h < 18:
        return "tarde (12-18)"
    return "noche (18-24)"


def leg_stats(legs):
    graded = [l for l in legs if l.get("result") in ("win", "loss")]
    w = sum(1 for l in graded if l["result"] == "win")
    return {"n": len(graded), "wins": w, "losses": len(graded) - w, "hit_rate": r(w / len(graded)) if graded else None, "muestra_chica": len(graded) < 10}


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    tickets = data.get("tickets", [])
    settled = [t for t in tickets if t.get("status") in SETTLED]
    open_t = [t for t in tickets if t.get("status") == "open"]

    by = lambda key: defaultdict(list)  # noqa: E731
    by_type, by_legs, by_book, by_hour, by_follow, by_week = by(0), by(0), by(0), by(0), by(0), by(0)
    boosts, free = [], []
    for t in settled:
        by_type[t.get("type", "?")].append(t)
        by_legs[legs_bucket(int(t.get("legs_count") or len(t.get("legs", []))))].append(t)
        by_book[t.get("book", "?")].append(t)
        by_hour[hour_bucket(t.get("placed_at", ""))].append(t)
        by_follow["siguiendo canal" if t.get("followed_channel") else "propio"].append(t)
        by_week[f"W{int(t.get('week') or 0):02d}"].append(t)
        if t.get("boost"):
            boosts.append(t)
        if t.get("free_bet"):
            free.append(t)

    # Legs
    all_legs = [dict(l, _ticket=t) for t in settled for l in t.get("legs", [])]
    by_cat, by_team, by_src = defaultdict(list), defaultdict(list), defaultdict(list)
    for l in all_legs:
        by_cat[l.get("category", "other")].append(l)
        if l.get("team"):
            by_team[l["team"]].append(l)
        by_src[l.get("source", "propio")].append(l)

    # Leg que me mata
    killer = defaultdict(int)
    one_leg_losses = 0
    lost_parlays = [t for t in settled if t["status"] == "lost" and len(t.get("legs", [])) >= 2 and t.get("legs_visible", True)]
    for t in lost_parlays:
        losers = [l for l in t["legs"] if l.get("result") == "loss"]
        if len(losers) == 1:
            one_leg_losses += 1
            killer[losers[0].get("category", "other")] += 1

    # Calibración por probabilidad implícita (legs con momio)
    bins = [(0.0, 0.4, "<40%"), (0.4, 0.55, "40-55%"), (0.55, 0.7, "55-70%"), (0.7, 1.01, ">70%")]
    calib = []
    for lo, hi, label in bins:
        ls = [l for l in all_legs if l.get("odds_decimal") and l.get("result") in ("win", "loss") and lo <= 1 / float(l["odds_decimal"]) < hi]
        if ls:
            w = sum(1 for l in ls if l["result"] == "win")
            calib.append({"bin": label, "n": len(ls), "prob_implicita_prom": r(sum(1 / float(l["odds_decimal"]) for l in ls) / len(ls)), "hit_rate": r(w / len(ls))})

    # Hit rate real vs implícita por número de legs (boletos con momio decimal)
    legs_vs_implied = {}
    for k, ts in by_legs.items():
        with_odds = [t for t in ts if t.get("odds_decimal")]
        st = group_stats(ts)
        st["prob_implicita_prom"] = r(sum(1 / float(t["odds_decimal"]) for t in with_odds) / len(with_odds)) if with_odds else None
        legs_vs_implied[k] = st

    cat_stats = {c: dict(leg_stats(ls), label=CATEGORY_LABELS.get(c, c)) for c, ls in by_cat.items()}

    # Qué sí / Qué no
    si, no, insuf = [], [], []
    for c, s in sorted(cat_stats.items(), key=lambda kv: -(kv[1]["n"])):
        if s["n"] < 3:
            insuf.append(f"{s['label']}: solo {s['n']} leg(s) calificadas. Muestra insuficiente.")
        elif s["hit_rate"] >= 0.6:
            si.append(f"{s['label']}: {s['wins']} de {s['n']} aciertos ({s['hit_rate']:.0%}). SÍ." + (" Muestra chica." if s["n"] < 10 else ""))
        elif s["hit_rate"] <= 0.34:
            no.append(f"{s['label']}: {s['wins']} de {s['n']} aciertos ({s['hit_rate']:.0%}). NO." + (" Muestra chica." if s["n"] < 10 else ""))
    for k, s in legs_vs_implied.items():
        if s["n"] >= 3 and s["hit_rate"] is not None and s["hit_rate"] <= 0.2:
            no.append(f"Boletos de {k} legs: {s['ganados']} de {s['n']} ganados. NO." + (" Muestra chica." if s["n"] < 10 else ""))
    hb = by_hour.get("madrugada (00-06)", [])
    if len(hb) >= 3:
        s = group_stats(hb)
        (no if (s["hit_rate"] or 0) <= 0.34 else si).append(f"Apuestas de madrugada: {s['ganados']} de {s['n']} ganadas. " + ("NO." if (s["hit_rate"] or 0) <= 0.34 else "OK."))

    out = {
        "generated_at": datetime.now().date().isoformat(),
        "n_boletos_total": len(tickets), "n_boletos_settled": len(settled), "n_boletos_open": len(open_t),
        "n_no_validados": sum(1 for t in tickets if not t.get("validated")),
        "advertencia_muestra": "Menos de 10 boletos liquidados: las métricas son orientativas." if len(settled) < 10 else None,
        "global": group_stats(settled),
        "por_tipo": {k: group_stats(v) for k, v in by_type.items()},
        "por_legs": legs_vs_implied,
        "por_casa": {k: group_stats(v) for k, v in by_book.items()},
        "por_horario": {k: group_stats(v) for k, v in by_hour.items()},
        "por_origen": {k: group_stats(v) for k, v in by_follow.items()},
        "por_semana": {k: group_stats(v) for k, v in sorted(by_week.items())},
        "boosts": group_stats(boosts), "apuestas_gratis": group_stats(free),
        "por_categoria_leg": cat_stats,
        "por_equipo_leg": {k: leg_stats(v) for k, v in sorted(by_team.items())},
        "por_fuente_leg": {k: leg_stats(v) for k, v in by_src.items()},
        "leg_que_me_mata": {"parlays_perdidos": len(lost_parlays), "perdidos_por_una_sola_leg": one_leg_losses,
                             "categoria_culpable": dict(sorted(killer.items(), key=lambda kv: -kv[1]))},
        "calibracion": calib,
        "que_si": si, "que_no": no, "muestra_insuficiente": insuf,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"global": out["global"], "que_si": si, "que_no": no, "insuficiente": insuf}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
