#!/usr/bin/env python3
"""Genera docs/data/ desde data/ para el sitio estático (GitHub Pages sirve /docs).

- Copia config, historial 2024/25, bankroll 2026, mis apuestas y su análisis.
- Para cada semana: cruza picks con mis tendencias (✓ tu fuerte / ⚠ tu débil, n >= 5),
  agrega comparación de momios y consenso entre canales.
- Escribe docs/data/index.json con las pestañas disponibles.
- Si config.site.show_amounts es false, quita los montos MXN de lo publicado.

Uso:  python scripts/build_site.py
"""
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, DOCS = ROOT / "data", ROOT / "docs" / "data"
sys.path.insert(0, str(ROOT / "scripts"))


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def dump(obj, p):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


# Claves cuyo valor numérico es un monto MXN. Solo se reemplazan escalares int/float (nunca listas ni dicts,
# que se recorren). Si el valor es una lista, sus elementos numéricos también se ocultan (deposito_detalle).
MONEY_KEYS = {
    "stake_mxn", "payout_mxn", "deposito", "retiro", "neto", "acumulado", "invertido_mxn", "cobrado_mxn", "profit_mxn",
    "deposito_total", "retiro_total", "neto_acumulado_mxn", "restante_antes_de_parar_mxn", "neto_mxn",
    "promedio_neto_semana", "peor_drawdown_en_racha", "peor_acumulado", "mejor_acumulado",
    "mxn", "presupuesto_semanal_mxn", "weekly_budget_mxn", "retiros_sin_asignar", "deposito_detalle", "contraste",
}
# El límite del stop loss es una regla, no un saldo: se publica siempre.
NEVER_HIDE = {"limite_perdida_mxn", "max_net_loss_mxn"}
# Claves de texto libre donde se enmascaran montos ("neto -383 MXN" -> "neto ••• MXN").
TEXT_KEYS = {"reglas_con_datos", "regla", "que_si", "que_no", "nota", "notas"}
AMOUNT_IN_TEXT = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?\s*MXN")
HIDDEN = "oculto"


def _is_amount(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _mask_text(v):
    if isinstance(v, str):
        return AMOUNT_IN_TEXT.sub("••• MXN", v)
    if isinstance(v, list):
        return [_mask_text(x) for x in v]
    return strip_amounts(v)


def _hide_money(v):
    if _is_amount(v):
        return HIDDEN
    if isinstance(v, list):
        return [HIDDEN if _is_amount(x) else strip_amounts(x) for x in v]
    return strip_amounts(v)


def strip_amounts(obj):
    """Copia de obj con los montos MXN ocultos (config.site.show_amounts false)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in NEVER_HIDE:
                out[k] = v
            elif k in MONEY_KEYS:
                out[k] = _hide_money(v)
            elif k in TEXT_KEYS:
                out[k] = _mask_text(v)
            else:
                out[k] = strip_amounts(v)
        return out
    if isinstance(obj, list):
        return [strip_amounts(x) for x in obj]
    return obj


def norm_sel(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def add_to_record(rec, p):
    """Suma un pick calificado al récord por canal (rec: {canal: récord}).

    W-L-P cuenta todos los picks con result win/loss/push. bets cuenta los de
    confidence alta o media (apuestas que el canal dijo haber hecho) y leans los de
    confidence baja (leans y picks de concurso). units solo se mueve con odds_decimal
    numérico: win suma odds_decimal - 1, loss resta 1, push 0. Sin momio el pick no
    afecta units ni cuenta en units_n.
    """
    res = p.get("result")
    if res not in ("win", "loss", "push"):
        return
    r = rec.setdefault(p.get("channel", "?"), {
        "win": 0, "loss": 0, "push": 0, "units": 0.0, "units_n": 0,
        "bets": {"win": 0, "loss": 0, "push": 0}, "leans": {"win": 0, "loss": 0, "push": 0}})
    r[res] += 1
    conf = str(p.get("confidence") or "").strip().lower()
    kind = "bets" if conf in ("alta", "media") else "leans" if conf == "baja" else None
    if kind:
        r[kind][res] += 1
    odds = p.get("odds_decimal")
    if isinstance(odds, (int, float)) and not isinstance(odds, bool) and 1 < odds < float("inf"):
        r["units_n"] += 1
        r["units"] = round(r["units"] + (odds - 1 if res == "win" else -1 if res == "loss" else 0), 2)


def main():
    cfg = load(DATA / "config.json")
    show = cfg.get("site", {}).get("show_amounts", True)
    # Recalcular derivados
    subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze_history.py")], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze_my_bets.py")], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "bankroll.py")], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "compare_odds.py")], check=True, capture_output=True)

    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)
    f = (lambda o: o) if show else strip_amounts
    dump(f(cfg), DOCS / "config.json")
    for name in ("bankroll_2024.json", "bankroll_2025.json", "distribucion_semanal.json", "analysis.json"):
        dump(f(load(DATA / "history" / name)), DOCS / "history" / name)
    dump(f(load(DATA / "bankroll_2026_status.json")), DOCS / "bankroll_2026_status.json")
    analysis = load(DATA / "my_bets_analysis.json")
    dump(f(analysis), DOCS / "my_bets_analysis.json")
    bets = load(DATA / "my_bets.json")
    bets.pop("_schema", None)
    dump(f(bets), DOCS / "my_bets.json")
    dump(load(ROOT / "channels.json"), DOCS / "channels.json")

    cat_stats = analysis.get("por_categoria_leg", {})
    weeks, record = [], {}
    for pf in sorted((DATA / "picks").glob("*-W*.json")):
        d = load(pf)
        odds_file = DATA / "odds" / pf.name
        comp = {c["pick_id"]: c for c in load(odds_file).get("comparison", [])} if odds_file.exists() else {}
        groups = defaultdict(list)
        for p in d.get("picks", []):
            cs = cat_stats.get(p.get("category"))
            if cs and cs["n"] >= 5 and cs["hit_rate"] is not None:
                p["cross"] = {"tag": "fuerte" if cs["hit_rate"] >= 0.55 else "debil" if cs["hit_rate"] <= 0.4 else "neutral", "hit_rate": cs["hit_rate"], "n": cs["n"]}
            else:
                p["cross"] = None
            p["odds_compare"] = comp.get(p["id"])
            groups[(p.get("game", ""), norm_sel(p.get("selection")))].append(p)
            add_to_record(record, p)
        d["consensus"] = [{"game": g, "selection": ps[0].get("selection"), "channels": sorted({p["channel"] for p in ps}), "pick_ids": [p["id"] for p in ps]}
                          for (g, _), ps in groups.items() if len({p["channel"] for p in ps}) >= 2]
        dump(d, DOCS / "picks" / pf.name)
        weeks.append({"season": d["season"], "week": d["week"], "file": f"picks/{pf.name}", "n_picks": len(d.get("picks", [])),
                      "n_videos": len(d.get("sources", [])), "status": d.get("status", "ok"), "generated_at": d.get("generated_at")})
    dump({"generated_at": datetime.now().date().isoformat(), "season": cfg["season"], "show_amounts": show,
          "weeks": sorted(weeks, key=lambda w: (w["season"], w["week"])), "channel_record": record}, DOCS / "index.json")
    # Validación
    for p in DOCS.rglob("*.json"):
        load(p)
    print(f"docs/data listo: {len(weeks)} semana(s), montos {'visibles' if show else 'ocultos'}")


if __name__ == "__main__":
    main()
