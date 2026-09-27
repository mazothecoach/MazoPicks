#!/usr/bin/env python3
"""Lista videos nuevos por canal (yt-dlp) y los guarda en data/videos_new.json.

Filtros: title_keywords del canal (sin distinguir mayúsculas), subidos en los últimos
--days días (default 8), duración >= 90 s (excluye Shorts) y que no estén en
data/videos_processed.json.

Uso:
  python scripts/fetch_videos.py [--days 8] [--max 25] [--ids ID1,ID2] [--force]
Con --ids cada ID se procesa una sola vez y su canal se asigna por la metadata de yt-dlp
(uploader_id, channel, uploader, channel_id contra handle, name y url de channels.json).
Si ninguno coincide se usa el primer canal activo y el registro lleva "channel_match": "fallback".
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


MATCH_FIELDS = ("uploader_id", "channel", "uploader", "channel_id")


def _key(s):
    """Normaliza para comparar sin distinguir mayúsculas (y sin @ inicial)."""
    return str(s or "").strip().lower().lstrip("@")


def channel_keys(ch):
    """handle, name y url del canal (url completa y su último segmento, ej. @KyleKirms o UC...)."""
    url = str(ch.get("url") or "").strip().rstrip("/")
    return {_key(ch.get("handle")), _key(ch.get("name")), _key(url), _key(url.rsplit("/", 1)[-1])} - {""}


def match_channel(meta, channels):
    """Primer canal de channels.json cuyo handle/name/url coincide con algún campo de yt-dlp, o None."""
    fields = {_key(meta.get(k)) for k in MATCH_FIELDS} - {""}
    for ch in channels:
        if fields & channel_keys(ch):
            return ch
    return None


def upload_day(m):
    up = m.get("upload_date")  # YYYYMMDD
    return datetime.strptime(up, "%Y%m%d").date() if up else None


def make_record(ch, vid, m, title_hint="", channel_match=None):
    dur = m.get("duration") or 0
    up_d = upload_day(m)
    title = m.get("title") or title_hint
    season, week, src = nfl_week.resolve(up_d or date.today(), title)
    tag = f" [canal: {channel_match}]" if channel_match else ""
    print(f"[nuevo] {ch['name']}{tag} | W{week:02d} ({src}) | {title} | {vid}")
    return {
        "channel": ch["name"],
        **({"channel_match": channel_match} if channel_match else {}),
        "video_id": vid,
        "title": title,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "published": up_d.isoformat() if up_d else None,
        "duration_s": dur,
        "season": season,
        "week": week,
        "week_source": src,
        "transcript_method": None,
    }


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
    active = [ch for ch in channels if ch.get("active", True)]

    if a.ids:
        # Cada ID una sola vez; el canal sale de la metadata del video, no del loop de canales.
        for vid in dict.fromkeys(v.strip() for v in a.ids.split(",") if v.strip()):
            if vid in processed and not a.force:
                continue
            m = video_meta(vid)
            if not m:
                continue
            dur = m.get("duration") or 0
            if dur and dur < 90:
                continue
            ch, how = match_channel(m, channels), None
            if ch is None:
                if not active:
                    print(f"[aviso] {vid}: ningún canal coincide y no hay canales activos; se omite", file=sys.stderr)
                    continue
                ch, how = active[0], "fallback"
            found.append(make_record(ch, vid, m, channel_match=how))
    else:
        for ch in active:
            kws = [k.lower() for k in ch.get("title_keywords", [])]
            candidates = []
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
                if dur and dur < 90:
                    continue
                up_d = upload_day(m)
                if up_d and up_d < cutoff:
                    continue
                found.append(make_record(ch, vid, m, c["title"]))

    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(found)} video(s) nuevo(s) -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
