#!/usr/bin/env python3
"""Fecha -> temporada y semana NFL.

La semana NFL corre de martes a lunes. La fecha del kickoff de la Semana 1 vive en
data/config.json (week1_kickoff). Si el título del video dice "Week N", ese número manda.

Uso:
  python scripts/nfl_week.py                 # hoy
  python scripts/nfl_week.py 2026-09-27
  python scripts/nfl_week.py 2026-09-27 "Week 3 NFL Picks with Kyle Kirms"
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "data" / "config.json").read_text(encoding="utf-8"))


def week1_tuesday():
    k = date.fromisoformat(CONFIG["week1_kickoff"])
    return k - timedelta(days=(k.weekday() - 1) % 7)


def season_week(d):
    """Devuelve (season, week). week=0 significa antes de la Semana 1 (pretemporada)."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    elif isinstance(d, datetime):
        d = d.date()
    delta = (d - week1_tuesday()).days
    if delta < 0:
        return CONFIG["season"], 0
    return CONFIG["season"], delta // 7 + 1


def week_from_title(title):
    m = re.search(r"\bweek\s*(\d{1,2})\b", title or "", re.I)
    return int(m.group(1)) if m else None


def resolve(d, title=None):
    """(season, week, fuente) donde fuente es 'title' o 'date'."""
    season, wk = season_week(d)
    t = week_from_title(title)
    if t:
        return season, t, "title"
    return season, wk, "date"


def week_dates(week):
    """(martes, lunes) de la semana NFL dada."""
    start = week1_tuesday() + timedelta(days=7 * (week - 1))
    return start, start + timedelta(days=6)


def picks_filename(season, week):
    return f"{season}-W{week:02d}.json"


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    title = sys.argv[2] if len(sys.argv) > 2 else None
    s, w, src = resolve(d, title)
    a, b = week_dates(w) if w else (None, None)
    print(json.dumps({"date": d, "season": s, "week": w, "source": src, "week_dates": [str(a), str(b)], "file": picks_filename(s, w)}))
