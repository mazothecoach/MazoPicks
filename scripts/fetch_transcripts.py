#!/usr/bin/env python3
"""Transcribe los videos de data/videos_new.json (o los IDs dados) con fallback:

  1. youtube-transcript-api (en, es)
  2. yt-dlp --write-auto-subs (VTT limpiado)
  3. gemini: baja el audio con yt-dlp (mp3, --force-overwrites) y lo transcribe con
     scripts/transcribe_gemini.py (API REST de Gemini, trozos con ffmpeg). Solo si GEMINI_API_KEY
     está definida; gasta cuota (free tier de gemini-2.5-flash: 20 requests/día, cada reintento
     cuenta) y al final se imprime cuántas llamadas hizo.
  4. Whisper local (faster-whisper o whisper CLI) si está instalado

Guarda data/transcripts/{video_id}.txt con encabezado (título, canal, fecha, url, método)
y líneas "[mm:ss] texto". Actualiza transcript_method en data/videos_new.json.

Uso (siempre con python -u, para no perder la salida si el proceso muere):
  python -u scripts/fetch_transcripts.py            # todos los de videos_new.json
  python -u scripts/fetch_transcripts.py 4o0fpns6Gm0 gM-02rLbR9w
Variables:
  GEMINI_API_KEY     activa el paso 3 (https://aistudio.google.com/apikey)
  WHISPER_MODEL      nombre o ruta del modelo (default "base")
  YTDLP_EXTRA_ARGS   argumentos extra para yt-dlp (las cookies ya salen del config de yt-dlp)
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcribe_gemini  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NEW = ROOT / "data" / "videos_new.json"
TDIR = ROOT / "data" / "transcripts"
GEMINI_LANG = "en"  # los canales de picks son en inglés
GEMINI_BUDGET = transcribe_gemini.Presupuesto()  # llamadas a Gemini en toda la corrida


class Omitido(Exception):
    """El método no aplica en esta compu (falta configuración); no es una falla del video."""


def fmt_ts(sec):
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def via_api(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise RuntimeError("youtube-transcript-api no está instalado (pip install -r requirements.txt)") from None
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
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp no está instalado o no está en el PATH")
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


def _tail(p):
    """Última línea útil de stderr de un proceso (para mensajes de error legibles)."""
    lines = [l.strip() for l in (p.stderr or "").splitlines() if l.strip()] if p else []
    return lines[-1][:200] if lines else "sin detalle"


def audio_mp3(tmp, video_id):
    """mp3 que dejó el paso gemini. Con -o ID.mp3 y -x, yt-dlp baja el stream (webm o m4a) como ID.mp3
    y el extractor escribe ID.mp3.mp3 (borra el original), así que se aceptan los dos nombres."""
    for name in (f"{video_id}.mp3.mp3", f"{video_id}.mp3"):
        path = Path(tmp) / name
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def via_gemini(video, tmp):
    """Método B del documento "Cómo Claude ve videos": audio mp3 con yt-dlp y transcripción con Gemini."""
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        raise Omitido("GEMINI_API_KEY no está definida; ver README")
    vid = video["video_id"]
    # Paso 2 del documento tal cual, en su propio comando (la metadata ya viene de fetch_videos.py;
    # combinarla con la descarga causa timeouts). Las cookies salen del config de yt-dlp.
    p = None
    try:
        p = subprocess.run(ytdlp_cmd(["-f", "bestaudio", "-x", "--audio-format", "mp3", "--audio-quality", "5",
                                      "--force-overwrites", "-o", str(Path(tmp) / f"{vid}.mp3"),
                                      f"https://www.youtube.com/watch?v={vid}"]),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired:
        pass  # a veces parece colgado en [ExtractAudio] con el archivo ya listo: se revisa abajo
    audio = audio_mp3(tmp, vid)
    if audio is None:
        raise RuntimeError(f"yt-dlp no descargó el audio ({_tail(p)}). Si dice 'Sign in to confirm', "
                           "las cookies expiraron: re-exportarlas")
    title = video.get("title") or ""
    context = (f"NFL betting picks video{': ' + title if title else ''}. "
               "Use the standard spelling of NFL teams and players.")
    antes = GEMINI_BUDGET.total
    try:
        res = transcribe_gemini.transcribe_audio(
            audio, lang=GEMINI_LANG, context=context, duration_hint=video.get("duration_s"),
            presupuesto=GEMINI_BUDGET, log=lambda m: print(f"  [gemini] {m}", flush=True))
    finally:
        video["gemini_calls"] = GEMINI_BUDGET.total - antes
        print(f"  [gemini] {vid}: {video['gemini_calls']} llamada(s) a generateContent", flush=True)
    for aviso in res.avisos:
        print(f"  [gemini] AVISO: {aviso}", flush=True)
    print(f"  [gemini] {res.verificacion}", flush=True)
    video["gemini_check"] = res.verificacion
    return [(s, t) for s, _e, t in res.segments]


def via_whisper(video_id, tmp):
    model = os.environ.get("WHISPER_MODEL", "base")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        WhisperModel = None
    if WhisperModel is None and not shutil.which("whisper"):
        raise RuntimeError("no hay faster-whisper ni whisper CLI instalados")
    audio = audio_mp3(tmp, video_id)  # si el paso gemini ya bajó el audio, se reutiliza
    if audio is None:
        audio = Path(tmp) / f"{video_id}.m4a"
        subprocess.run(ytdlp_cmd(["-x", "--audio-format", "m4a", "-o", str(Path(tmp) / "%(id)s.%(ext)s"),
                                  f"https://www.youtube.com/watch?v={video_id}"]), capture_output=True, text=True)
        if not audio.exists():
            raise RuntimeError("yt-dlp no descargó el audio")
    if WhisperModel is not None:
        wm = WhisperModel(model)
        segments, _ = wm.transcribe(str(audio))
        return [(s.start, s.text.strip()) for s in segments]
    subprocess.run(["whisper", str(audio), "--model", model, "--output_format", "vtt", "--output_dir", tmp],
                   capture_output=True, text=True)
    vtt = Path(tmp) / f"{audio.stem}.vtt"
    if vtt.exists():
        return parse_vtt(vtt)
    raise RuntimeError("whisper CLI no generó el VTT")


def transcribe(video):
    vid = video["video_id"]
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in (("youtube-transcript-api", lambda: via_api(vid)),
                         ("yt-dlp-auto-subs", lambda: via_subs(vid, tmp)),
                         ("gemini", lambda: via_gemini(video, tmp)),
                         ("whisper-local", lambda: via_whisper(vid, tmp))):
            try:
                segs = fn()
                if segs:
                    return name, segs, errors
                errors.append(f"{name}: vacío")
            except Omitido as e:
                errors.append(f"{name}: omitido ({e})")
            except Exception as e:  # noqa: BLE001
                msg = " ".join(str(e).split())[:300]
                errors.append(f"{name}: {type(e).__name__}: {msg}")
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
    if os.environ.get("GEMINI_API_KEY", "").strip():
        print(GEMINI_BUDGET.resumen())


if __name__ == "__main__":
    main()
