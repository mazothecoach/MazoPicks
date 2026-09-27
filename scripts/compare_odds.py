#!/usr/bin/env python3
"""Compara momios Draftea vs Playdoit por pick (data/odds/{season}-W{nn}.json).

Cada entrada: {"pick_id", "book", "odds_decimal" | "odds_american", "captured_at", "source"}.
Escribe "comparison": mejor casa por pick, diferencia % y probabilidad implícita.

Uso:  python scripts/compare_odds.py [2026-W03]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ODDS = ROOT / "data" / "odds"


def american_to_decimal(a):
    a = float(a)
    return round(1 + (a / 100 if a > 0 else 100 / abs(a)), 3)


def decimal_to_american(d):
    d = float(d)
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def normalize(e):
    if e.get("odds_decimal"):
        return float(e["odds_decimal"])
    if e.get("odds_american") is not None:
        return american_to_decimal(e["odds_american"])
    return None


def compare_file(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    per_pick = defaultdict(dict)
    for e in d.get("entries", []):
        dec = normalize(e)
        if dec:
            per_pick[e["pick_id"]][e["book"]] = {"decimal": dec, "american": decimal_to_american(dec), "captured_at": e.get("captured_at"), "source": e.get("source")}
    comp = []
    for pid, books in per_pick.items():
        best_book = max(books, key=lambda b: books[b]["decimal"])
        best = books[best_book]["decimal"]
        worst = min(v["decimal"] for v in books.values())
        comp.append({
            "pick_id": pid, "books": books, "best_book": best_book, "best_decimal": best,
            "diff_pct_vs_peor": round((best / worst - 1) * 100, 2) if len(books) > 1 else None,
            "prob_implicita_mejor": round(1 / best, 3),
            "n_casas": len(books),
        })
    d["comparison"] = sorted(comp, key=lambda c: c["pick_id"])
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def main():
    files = [ODDS / f"{sys.argv[1]}.json"] if len(sys.argv) > 1 else sorted(ODDS.glob("*-W*.json"))
    for f in files:
        d = compare_file(f)
        print(f"{f.name}: {len(d['comparison'])} pick(s) con momios, {len(d.get('entries', []))} entradas")


if __name__ == "__main__":
    main()
