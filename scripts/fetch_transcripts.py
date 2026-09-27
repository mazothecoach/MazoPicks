#!/usr/bin/env python3
"""Transcribe los videos de data/videos_new.json (o los IDs dados) con fallback:

  1. youtube-transcript-api (en, es)
  2. yt-dlp --write-auto-subs (VTT limpiado)
  3. Whisper local (faster-whisper o whisper CLI) si está instalado

Guarda data/transcripts/{video_id}.txt con encabezado (título, canal, fecha, url, método)
y líneas "[mm:ss] texto". Actualiza transcript_method en data/videos_new.json.

Uso:
  python scripts/fetch_transcripts.py            # todos los de videos_new.json
  python scripts/fetch_transcripts.py 4o0fpns6Gm0 gM-02rLbR9w
Variables:
  WHISPER_MODEL      nombre o ruta del modelo (default "base")
  YTDLP_EXTRA_ARGS   argumentos extra para yt-dlp
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEW = ROOT / "data" / "videos_new.json"
TDIR = ROOT / "data" / "transcripts"


def fmt_ts(sec):
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def via_api(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["en", "es"])
        return [(s.start, s.text) for s in fetched]
    except AttributeError:  # versiones viejas (< 1.0)
        return [(s["start"], s["text"]) for s in YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "es"])]


def parse_vtt(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    segs, last = [], None
    blocks = re.split(r"\n\s*\n", text)
    for b in blocks:
        lines = [l for l in b.strip().splitlines() if l.strip()]
        if not lines:
            continue
        m = re.search(r"(\d+):(\d+):(\d+)[.,](\d+)\s*-->", lines[0]) or (len(lines) > 1 and re.search(r"(\d+):(\d+):(\d+)[.,](\d+)\s*-->", lines[1]))
        if not m:
            continue
        start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        body = " ".join(l for l in lines if "-->" not in l and not l.startswith(("WEBVTT", "Kind:", "Language:")))
        body = re.sub(r"<[^>]+>", "", body).replace("&nbsp;", " ").strip()
        if not body or body == last:
            continue
        last = body
        segs.append((start, body))
    return segs


def ytdlp_cmd(args):
    extra = shlex.split(os.environ.get("YTDLP_EXTRA_ARGS", ""))
    return ["yt-dlp", *extra, *args]


def via_subs(video_id, tmp):
    subprocess.run(ytdlp_cmd(["--write-auto-subs", "--write-subs", "--sub-langs", "en.*,en,es", "--skip-download",
                              "-o", str(Path(tmp) / "%(id)s"), f"https://www.youtube.com/watch?v={video_id}"]),
                   capture_output=True, text=True)
    vtts = sorted(Path(tmp).glob(f"{video_id}*.vtt"))
    if not vtts:
        raise RuntimeError("yt-dlp no generó subtítulos")
    return parse_vtt(vtts[0])


def via_whisper(video_id, tmp):
    audio = Path(tmp) / f"{video_id}.m4a"
    subprocess.run(ytdlp_cmd(["-x", "--audio-format", "m4a", "-o", str(Path(tmp) / "%(id)s.%(ext)s"),
                              f"https://www.youtube.com/watch?v={video_id}"]), capture_output=True, text=True)
    if not audio.exists():
        raise RuntimeError("yt-dlp no descargó el audio")
    model = os.environ.get("WHISPER_MODEL", "base")
    try:
        from faster_whisper import WhisperModel
        wm = WhisperModel(model)
        segments, _ = wm.transcribe(str(audio))
        return [(s.start, s.text.strip()) for s in segments]
    except ImportError:
        pass
    if shutil.which("whisper"):
        subprocess.run(["whisper", str(audio), "--model", model, "--output_format", "vtt", "--output_dir", tmp],
                       capture_output=True, text=True)
        vtt = Path(tmp) / f"{video_id}.vtt"
        if vtt.exists():
            return parse_vtt(vtt)
    raise RuntimeError("no hay faster-whisper ni whisper CLI instalados")


def transcribe(video):
    vid = video["video_id"]
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in (("youtube-transcript-api", lambda: via_api(vid)),
                         ("yt-dlp-auto-subs", lambda: via_subs(vid, tmp)),
                         ("whisper-local", lambda: via_whisper(vid, tmp))):
            try:
                segs = fn()
                if segs:
                    return name, segs, errors
                errors.append(f"{name}: vacío")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
    return None, [], errors


def write_transcript(video, method, segs):
    TDIR.mkdir(parents=True, exist_ok=True)
    out = TDIR / f"{video['video_id']}.txt"
    head = [
        f"# title: {video.get('title', '')}",
        f"# channel: {video.get('channel', '')}",
        f"# published: {video.get('published', '')}",
        f"# url: {video.get('url', '')}",
        f"# season_week: {video.get('season', '')}-W{int(video.get('week') or 0):02d}",
        f"# transcript_method: {method}",
        "",
    ]
    body = [f"[{fmt_ts(s)}] {t}" for s, t in segs]
    out.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    return out


def main():
    videos = json.loads(NEW.read_text(encoding="utf-8")) if NEW.exists() else []
    ids = sys.argv[1:]
    if ids:
        known = {v["video_id"]: v for v in videos}
        videos = [known.get(i, {"video_id": i, "url": f"https://www.youtube.com/watch?v={i}"}) for i in ids]
    if not videos:
        print("Nada que transcribir (data/videos_new.json vacío). Corre fetch_videos.py primero.")
        return
    ok = 0
    for v in videos:
        method, segs, errors = transcribe(v)
        if method:
            out = write_transcript(v, method, segs)
            v["transcript_method"] = method
            ok += 1
            print(f"[ok] {v['video_id']} via {method} ({len(segs)} segmentos) -> {out.relative_to(ROOT)}")
        else:
            v["transcript_method"] = None
            v["transcript_errors"] = errors
            print(f"[FALLÓ] {v['video_id']}: " + " | ".join(errors))
    if not ids:
        NEW.write_text(json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{ok}/{len(videos)} transcritos")


if __name__ == "__main__":
    main()
