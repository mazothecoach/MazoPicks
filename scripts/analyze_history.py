#!/usr/bin/env python3
"""Analiza el historial 2024 y 2025 (data/history/bankroll_*.json) y genera
data/history/analysis.json con métricas comparables por temporada, fase y mes.

Uso:  python scripts/analyze_history.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "history"


def r2(x):
    return round(float(x), 2)


def summarize_weeks(weeks):
    dep = sum(w["deposito"] for w in weeks)
    ret = sum(w["retiro"] for w in weeks)
    played = [w for w in weeks if w["deposito"] > 0]
    wins = [w for w in played if w["retiro"] - w["deposito"] > 0]
    losses = [w for w in played if w["retiro"] - w["deposito"] < 0]
    zero_ret = [w for w in played if w["retiro"] == 0]
    return {
        "n_semanas_jugadas": len(played),
        "deposito": r2(dep),
        "retiro": r2(ret),
        "neto": r2(ret - dep),
        "roi": r2((ret - dep) / dep) if dep else None,
        "semanas_ganadoras": len(wins),
        "semanas_perdedoras": len(losses),
        "semanas_sin_retiro": len(zero_ret),
        "hit_rate_semanal": r2(len(wins) / len(played)) if played else None,
        "promedio_neto_semana": r2((ret - dep) / len(played)) if played else None,
        "mejor_semana": max(played, key=lambda w: w["retiro"] - w["deposito"])["label"] if played else None,
        "peor_semana": min(played, key=lambda w: w["retiro"] - w["deposito"])["label"] if played else None,
    }


def streaks(weeks):
    """Rachas de semanas perdedoras consecutivas (solo semanas jugadas)."""
    played = [w for w in weeks if w["deposito"] > 0]
    best, cur, cur_loss = 0, 0, 0.0
    worst_loss = 0.0
    for w in played:
        net = w["retiro"] - w["deposito"]
        if net < 0:
            cur += 1
            cur_loss += net
            if cur > best:
                best = cur
            if cur_loss < worst_loss:
                worst_loss = cur_loss
        else:
            cur, cur_loss = 0, 0.0
    return {"max_semanas_perdedoras_seguidas": best, "peor_drawdown_en_racha": r2(worst_loss)}


def cumulative(weeks):
    acc, out = 0.0, []
    for w in weeks:
        acc += w["retiro"] - w["deposito"]
        out.append({"label": w["label"], "neto": r2(w["retiro"] - w["deposito"]), "acumulado": r2(acc)})
    return out


def analyze(season_file):
    d = json.loads(season_file.read_text(encoding="utf-8"))
    weeks = d["weeks"]
    by_phase = {}
    for ph in ("pre", "reg", "post"):
        ws = [w for w in weeks if w["phase"] == ph]
        if ws:
            by_phase[ph] = summarize_weeks(ws)
    reg = [w for w in weeks if w["phase"] == "reg"]
    early = [w for w in reg if w["label"] in ("Week 1", "Week 2", "Week 3", "Week 4")]
    mid = [w for w in reg if w["label"] in ("Week 5", "Week 6", "Week 7", "Week 8", "Week 9", "Week 10", "Week 11", "Week 12")]
    late = [w for w in reg if w["label"] in ("Week 13", "Week 14", "Week 15", "Week 16", "Week 17", "Week 18")]
    months = []
    for m in d["months"]:
        months.append({
            "month": m["month"], "deposito": m["deposito"], "retiro": m["retiro"],
            "neto": r2(m["retiro"] - m["deposito"]),
            "roi": r2((m["retiro"] - m["deposito"]) / m["deposito"]) if m["deposito"] else None,
        })
    cum = cumulative(weeks)
    return {
        "season": d["season"],
        "global": summarize_weeks(weeks),
        "por_fase": by_phase,
        "temporada_regular_por_tramo": {
            "temprano_w1_w4": summarize_weeks(early),
            "medio_w5_w12": summarize_weeks(mid),
            "tarde_w13_w18": summarize_weeks(late),
        },
        "rachas": streaks(weeks),
        "meses": months,
        "acumulado": cum,
        "peor_acumulado": r2(min(c["acumulado"] for c in cum)),
        "mejor_acumulado": r2(max(c["acumulado"] for c in cum)),
        "stopped_after": d.get("stopped_after"),
        "lessons_learned": d.get("lessons_learned", []),
    }


def main():
    seasons = []
    for f in sorted(HIST.glob("bankroll_20*.json")):
        seasons.append(analyze(f))
    if not seasons:
        print("No hay archivos data/history/bankroll_20*.json", file=sys.stderr)
        sys.exit(1)

    # Reglas derivadas (con sus números) para 2026
    rules = []
    for s in seasons:
        y = s["season"]
        pre = s["por_fase"].get("pre")
        early = s["temporada_regular_por_tramo"]["temprano_w1_w4"]
        mid = s["temporada_regular_por_tramo"]["medio_w5_w12"]
        if pre:
            rules.append(f"{y} pretemporada: neto {pre['neto']:+,.0f} MXN en {pre['n_semanas_jugadas']} semanas (hit rate semanal {pre['hit_rate_semanal']:.0%}).")
        rules.append(f"{y} semanas 1 a 4: neto {early['neto']:+,.0f} MXN, {early['semanas_ganadoras']} de {early['n_semanas_jugadas']} semanas ganadoras.")
        rules.append(f"{y} semanas 5 a 12: neto {mid['neto']:+,.0f} MXN, {mid['semanas_ganadoras']} de {mid['n_semanas_jugadas']} semanas ganadoras.")
        rules.append(f"{y} racha más larga de semanas perdedoras: {s['rachas']['max_semanas_perdedoras_seguidas']} (drawdown {s['rachas']['peor_drawdown_en_racha']:+,.0f} MXN).")

    out = {
        "generated_from": [str(f.name) for f in sorted(HIST.glob("bankroll_20*.json"))],
        "seasons": seasons,
        "reglas_con_datos": rules,
        "combined": {
            "deposito": r2(sum(s["global"]["deposito"] for s in seasons)),
            "retiro": r2(sum(s["global"]["retiro"] for s in seasons)),
            "neto": r2(sum(s["global"]["neto"] for s in seasons)),
        },
    }
    (HIST / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"seasons": [(s["season"], s["global"]) for s in seasons], "combined": out["combined"]}, ensure_ascii=False, indent=2))
    for rline in rules:
        print("-", rline)


if __name__ == "__main__":
    main()
