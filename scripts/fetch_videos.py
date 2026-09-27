#!/usr/bin/env python3
"""Lista videos nuevos por canal (yt-dlp) y los guarda en data/videos_new.json.

Filtros: title_keywords del canal (sin distinguir mayúsculas), subidos en los últimos
--days días (default 8), duración >= 90 s (excluye Shorts) y que no estén en
data/videos_processed.json.

Uso:
  python scripts/fetch_videos.py [--days 8] [--max 25] [--ids ID1,ID2]
Variables:
  YTDLP_EXTRA_ARGS  argumentos extra para yt-dlp (ej. "--cookies-from-browser chrome")
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nfl_week  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHANNELS = ROOT / "channels.json"
PROCESSED = ROOT / "data" / "videos_processed.json"
OUT = ROOT / "data" / "videos_new.json"


def ytdlp(args):
    extra = shlex.split(os.environ.get("YTDLP_EXTRA_ARGS", ""))
    cmd = ["yt-dlp", *extra, *args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(f"[yt-dlp] error ({p.returncode}): {p.stderr.strip()[-400:]}", file=sys.stderr)
    return p.stdout


def flat_list(url, n):
    out = ytdlp(["--flat-playlist", "--dump-json", "--playlist-end", str(n), f"{url}/videos"])
    for line in out.splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                pass


def video_meta(video_id):
    out = ytdlp(["-J", "--skip-download", "--no-playlist", f"https://www.youtube.com/watch?v={video_id}"])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("--ids", help="IDs separados por coma; salta el descubrimiento y usa estos videos")
    ap.add_argument("--force", action="store_true", help="incluye videos ya procesados")
    a = ap.parse_args()

    channels = json.loads(CHANNELS.read_text(encoding="utf-8"))
    processed = json.loads(PROCESSED.read_text(encoding="utf-8")) if PROCESSED.exists() else {}
    cutoff = date.today() - timedelta(days=a.days)
    found = []

    for ch in channels:
        if not ch.get("active", True):
            continue
        kws = [k.lower() for k in ch.get("title_keywords", [])]
        candidates = []
        if a.ids:
            candidates = [{"id": v, "title": ""} for v in a.ids.split(",")]
        else:
            for e in flat_list(ch["url"], a.max):
                vid, title = e.get("id"), e.get("title", "")
                if not vid:
                    continue
                if kws and not any(k in title.lower() for k in kws):
                    continue
                candidates.append({"id": vid, "title": title})
        for c in candidates:
            vid = c["id"]
            if vid in processed and not a.force:
                continue
            m = video_meta(vid)
            if not m:
                continue
            dur = m.get("duration") or 0
            up = m.get("upload_date")  # YYYYMMDD
            up_d = datetime.strptime(up, "%Y%m%d").date() if up else None
            if dur and dur < 90:
                continue
            if not a.ids and up_d and up_d < cutoff:
                continue
            title = m.get("title") or c["title"]
            season, week, src = nfl_week.resolve(up_d or date.today(), title)
            found.append({
                "channel": ch["name"],
                "video_id": vid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "published": up_d.isoformat() if up_d else None,
                "duration_s": dur,
                "season": season,
                "week": week,
                "week_source": src,
                "transcript_method": None,
            })
            print(f"[nuevo] {ch['name']} | W{week:02d} ({src}) | {title} | {vid}")

    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(found)} video(s) nuevo(s) -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
