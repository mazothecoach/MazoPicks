#!/usr/bin/env python3
"""Bankroll 2026 con stop loss.

Lee data/bankroll_2026.json (ledger semanal depósito/retiro, mismo modelo que NFL BETS.xlsx)
y data/config.json (stop_loss). Escribe data/bankroll_2026_status.json.

Uso:
  python scripts/bankroll.py                     # status
  python scripts/bankroll.py set --week 3 --deposito 1500 --retiro 400
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "bankroll_2026.json"
CONFIG = ROOT / "data" / "config.json"
BETS = ROOT / "data" / "my_bets.json"
OUT = ROOT / "data" / "bankroll_2026_status.json"


def compute():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    limit = float(cfg["stop_loss"]["max_net_loss_mxn"])
    acc, rows = 0.0, []
    for w in ledger["weeks"]:
        net = float(w.get("retiro", 0)) - float(w.get("deposito", 0))
        acc += net
        rows.append(dict(w, neto=round(net, 2), acumulado=round(acc, 2)))
    played = [w for w in rows if w.get("filled") or w.get("deposito", 0) > 0]
    net_total = round(acc, 2)
    remaining = round(limit + net_total, 2)  # cuánto puedo perder todavía
    if net_total <= -limit:
        level, status = "detenido", "DETENIDO"
    else:
        level = "verde"
        for lv in cfg["stop_loss"]["warning_levels"]:
            if lv["to_net"] < net_total <= lv["from_net"]:
                level = lv["label"]
        status = "ACTIVO"
    # Cruce con boletos liquidados (no es la fuente de verdad, solo contraste)
    tickets_net, tickets_n = 0.0, 0
    if BETS.exists():
        for t in json.loads(BETS.read_text(encoding="utf-8")).get("tickets", []):
            if t.get("status") in ("won", "lost", "cashed_out", "void"):
                stake = 0.0 if t.get("free_bet") else float(t.get("stake_mxn") or 0)
                tickets_net += float(t.get("payout_mxn") or 0) - stake
                tickets_n += 1
    weekly_budget = float(cfg.get("weekly_budget_mxn") or 0)
    return {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "season": ledger["season"],
        "limite_perdida_mxn": limit,
        "neto_acumulado_mxn": net_total,
        "restante_antes_de_parar_mxn": max(remaining, 0.0),
        "pct_del_limite_usado": round(min(max(-net_total, 0) / limit, 1.0), 3) if limit else None,
        "nivel": level,
        "estado": status,
        "semanas_capturadas": len(played),
        "semanas_ganadoras": sum(1 for w in played if w["neto"] > 0),
        "semanas_perdedoras": sum(1 for w in played if w["neto"] < 0),
        "deposito_total": round(sum(w["deposito"] for w in rows), 2),
        "retiro_total": round(sum(w["retiro"] for w in rows), 2),
        "presupuesto_semanal_mxn": weekly_budget,
        "semanas_de_presupuesto_restantes": round(max(remaining, 0) / weekly_budget, 1) if weekly_budget else None,
        "contraste_boletos": {"n_liquidados": tickets_n, "neto_mxn": round(tickets_net, 2),
                              "nota": "Neto según boletos extraídos de capturas. La fuente de verdad es el ledger semanal."},
        "regla": f"Si el neto acumulado llega a -{limit:,.0f} MXN se deja de apostar el resto de la temporada.",
        "weeks": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("set")
    s.add_argument("--week", type=int, required=True)
    s.add_argument("--deposito", type=float, default=None)
    s.add_argument("--retiro", type=float, default=None)
    a = ap.parse_args()
    if a.cmd == "set":
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        for w in ledger["weeks"]:
            if w["idx"] == a.week:
                if a.deposito is not None:
                    w["deposito"] = a.deposito
                if a.retiro is not None:
                    w["retiro"] = a.retiro
                w["filled"] = True
                break
        else:
            raise SystemExit(f"No existe la semana idx={a.week}")
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    st = compute()
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{st['estado']} / {st['nivel']}] neto {st['neto_acumulado_mxn']:+,.0f} MXN | restante {st['restante_antes_de_parar_mxn']:,.0f} MXN | semanas capturadas {st['semanas_capturadas']}")


if __name__ == "__main__":
    main()
