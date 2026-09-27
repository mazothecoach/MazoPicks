#!/usr/bin/env python3
"""Bankroll 2026 con stop loss.

Lee data/bankroll_2026.json (ledger semanal depósito/retiro, mismo modelo que NFL BETS.xlsx)
y data/config.json (stop_loss). Escribe data/bankroll_2026_status.json.

Reglas del ledger:
- retiro null = no se conoce el retiro de esa semana (pendiente). El neto de esa semana queda null.
- retiros_sin_asignar (nivel ledger) = retiros reales sin desglose por semana. Cuentan en el neto
  total (y por lo tanto en el stop loss), no en el neto de ninguna semana. En el acumulado entran en
  la última semana con depósito > 0 (fila marcada con acumulado_incluye_sin_asignar) y se arrastran.

Uso:
  python scripts/bankroll.py                     # status
  python scripts/bankroll.py set --week 3 --deposito 1500 --retiro 400
  python scripts/bankroll.py set --week 3 --retiro 0          # retiro conocido en 0
  python scripts/bankroll.py set --week 3 --retiro null       # retiro pendiente (desconocido)
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

NOTA_RETIROS = ("Los retiros sin asignar sí cuentan en el neto total y en el stop loss, pero no en el neto de ninguna semana "
                "porque no se sabe en qué semana se hicieron. Las semanas con retiro pendiente muestran neto pendiente; "
                "en el acumulado, los retiros sin asignar entran en la última semana con depósito.")


def num(v):
    """Número o None (retiro desconocido)."""
    return None if v is None else float(v)


def compute():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    limit = float(cfg["stop_loss"]["max_net_loss_mxn"])
    unassigned = float(ledger.get("retiros_sin_asignar") or 0)
    weeks = ledger["weeks"]
    # Semana donde entran los retiros sin asignar en el acumulado: la última con depósito > 0
    anchor = None
    for i, w in enumerate(weeks):
        if float(w.get("deposito") or 0) > 0:
            anchor = i
    acc, rows = 0.0, []
    for i, w in enumerate(weeks):
        dep = float(w.get("deposito") or 0)
        ret = num(w.get("retiro"))
        net = None if ret is None else round(ret - dep, 2)
        acc += (ret or 0.0) - dep
        row = dict(w, neto=net)
        if unassigned and i == anchor:
            acc += unassigned
            row["acumulado_incluye_sin_asignar"] = True
        row["acumulado"] = round(acc, 2)
        rows.append(row)
    played = [w for w in rows if w.get("filled") or float(w.get("deposito") or 0) > 0]
    dep_total = round(sum(float(w.get("deposito") or 0) for w in rows), 2)
    ret_known = round(sum(float(w["retiro"]) for w in rows if w.get("retiro") is not None), 2)
    net_total = round(ret_known + unassigned - dep_total, 2)
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
    pending = sum(1 for w in rows if float(w.get("deposito") or 0) > 0 and w.get("retiro") is None)
    # max(0.0, x) antes de dividir: si x es -0.0, max devuelve el 0.0 positivo (nunca -0.0)
    used = round(min(max(0.0, -net_total) / limit, 1.0), 3) if limit else None
    return {
        "generated_at": datetime.now().date().isoformat(),
        "season": ledger["season"],
        "limite_perdida_mxn": limit,
        "neto_acumulado_mxn": net_total,
        "restante_antes_de_parar_mxn": max(0.0, remaining),
        "pct_del_limite_usado": used,
        "nivel": level,
        "estado": status,
        "semanas_capturadas": len(played),
        "semanas_ganadoras": sum(1 for w in played if w["neto"] is not None and w["neto"] > 0),
        "semanas_perdedoras": sum(1 for w in played if w["neto"] is not None and w["neto"] < 0),
        "semanas_con_retiro_pendiente": pending,
        "deposito_total": dep_total,
        "retiro_total": round(ret_known + unassigned, 2),
        "retiros_sin_asignar": unassigned,
        "retiros_sin_asignar_nota": ledger.get("retiros_sin_asignar_nota"),
        "nota_retiros": NOTA_RETIROS,
        "presupuesto_semanal_mxn": weekly_budget,
        "semanas_de_presupuesto_restantes": round(max(0.0, remaining) / weekly_budget, 1) if weekly_budget else None,
        "contraste_boletos": {"n_liquidados": tickets_n, "neto_mxn": round(tickets_net, 2),
                              "nota": "Neto según boletos extraídos de capturas. La fuente de verdad es el ledger semanal."},
        "regla": f"Si el neto acumulado llega a -{limit:,.0f} MXN se deja de apostar el resto de la temporada.",
        "weeks": rows,
    }


def amount_or_null(s):
    """--retiro acepta un número o null/pendiente (retiro desconocido)."""
    if s.strip().lower() in ("null", "none", "pendiente"):
        return None
    try:
        return float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"monto inválido: {s!r} (usa un número o null)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("set")
    s.add_argument("--week", type=int, required=True)
    s.add_argument("--deposito", type=float, default=None)
    s.add_argument("--retiro", type=amount_or_null, default=argparse.SUPPRESS,
                   help="retiro de la semana (0 si se sabe que fue 0; null si no se conoce)")
    a = ap.parse_args()
    if a.cmd == "set":
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        for w in ledger["weeks"]:
            if w["idx"] == a.week:
                if a.deposito is not None:
                    w["deposito"] = a.deposito
                    det = w.get("deposito_detalle")
                    if det and round(sum(det), 2) != round(a.deposito, 2):
                        print(f"Aviso: deposito_detalle de idx={a.week} suma {sum(det):,.2f} y no {a.deposito:,.2f}. Corrígelo en el ledger.")
                if hasattr(a, "retiro"):
                    w["retiro"] = a.retiro
                w["filled"] = True
                break
        else:
            raise SystemExit(f"No existe la semana idx={a.week}")
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    st = compute()
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    extra = ""
    if st["retiros_sin_asignar"]:
        extra += f" | retiros sin asignar {st['retiros_sin_asignar']:,.0f} MXN"
    if st["semanas_con_retiro_pendiente"]:
        extra += f" | semanas con retiro pendiente {st['semanas_con_retiro_pendiente']}"
    print(f"[{st['estado']} / {st['nivel']}] neto {st['neto_acumulado_mxn']:+,.0f} MXN | restante {st['restante_antes_de_parar_mxn']:,.0f} MXN | semanas capturadas {st['semanas_capturadas']}{extra}")


if __name__ == "__main__":
    main()
