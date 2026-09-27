#!/usr/bin/env python3
"""Transcribe un audio con la API REST de Gemini (sin SDK) y escribe líneas "[mm:ss] texto".

Es el camino B del documento "Cómo Claude ve videos" (probado por Mazo en 6 episodios):
  1. Corta el audio en trozos de --chunk segundos con ffmpeg (default 480) y suma el offset de cada trozo.
  2. Sube cada trozo a la Gemini Files API (protocolo resumable).
  3. Pide models/{model}:generateContent con responseSchema JSON [{start_sec, end_sec, text}]:
     timestamps NUMBER (nunca string HH:MM:SS), maxOutputTokens 65536 y el thinking sin tocar
     (con thinkingBudget=0 Gemini degenera en basura repetida).
  4. Si una respuesta se trunca, rescata los segmentos completos y corta el resto con ffmpeg
     (nunca le pide a Gemini que agrupe turnos). Sin nada rescatable, parte el trozo en trozos de 90 s.
  5. Verifica que el primer timestamp esté cerca de 00:00 y el último cerca de la duración real
     (ffprobe si existe; si no, la duración de la metadata o la suma de los trozos).

Reintentos: 5xx (503 "high demand") y errores de red hasta 3 veces con backoff de 20 s (20, 40, 60).
429 de cuota cambia a --fallback-model. El free tier de gemini-2.5-flash son 20 requests/día reales y
cada reintento cuenta, así que al final se imprime cuántas llamadas se hicieron.

Uso (siempre con python -u, para no perder la salida si el proceso muere):
  python -u scripts/transcribe_gemini.py --audio x.mp3 --out data/transcripts/ID.txt --lang en
  python -u scripts/transcribe_gemini.py --audio x.mp3 --out x.txt --chunk 90 --context "Jordan Love, Bijan Robinson"
Variables:
  GEMINI_API_KEY   API key de https://aistudio.google.com/apikey (obligatoria)
Requiere ffmpeg en el PATH para cortar trozos (--chunk 0 manda el audio completo en una sola llamada).
ffprobe es opcional: da la duración real para la verificación.
"""
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

import requests

API_ROOT = "https://generativelanguage.googleapis.com"
API = f"{API_ROOT}/v1beta"
UPLOAD_URL = f"{API_ROOT}/upload/v1beta/files"

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_FALLBACK = "gemini-3.5-flash-lite"  # cuota independiente; gemini-2.5-flash-lite ya no existe
DEFAULT_LANG = "en"                         # los canales de picks son en inglés
DEFAULT_CHUNK = 480                         # segundos por trozo
SPLIT_TRUNCADO = 90                         # trozos de ~90 s cuando una respuesta se trunca sin rescate
MIN_TROZO_S = 2                             # un trozo más corto no se manda (no gasta cuota)
MAX_OUTPUT_TOKENS = 65536
REINTENTOS = 3
BACKOFF_S = 20
FREE_TIER_RPD = 20
TOL_INICIO_S = 30                           # el primer timestamp debe caer antes de esto
TOL_FIN_S = 60                              # el último, a menos de esto (o 3 %) de la duración real

LANGS = {"en": "English", "es": "Spanish"}
MIMES = {".mp3": "audio/mp3", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac",
         ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac", ".webm": "audio/webm"}

# Timestamps como NUMBER: pedirlos como string deriva en formatos inválidos tipo "04:34:80".
RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "start_sec": {"type": "NUMBER"},
            "end_sec": {"type": "NUMBER"},
            "text": {"type": "STRING"},
        },
        "required": ["start_sec", "end_sec", "text"],
        "propertyOrdering": ["start_sec", "end_sec", "text"],
    },
}

PROMPT = (
    "Transcribe this audio verbatim, in the language actually spoken (expected: {language}). "
    "Do not translate, summarize or skip anything.\n"
    "Return a JSON array in chronological order. Each item is one natural sentence or short speaker turn, "
    "exactly as it happens in the audio. Do not merge turns into longer blocks.\n"
    "start_sec and end_sec are numbers: seconds from the start of THIS audio file{bounds}.\n"
    "text is the exact words spoken in that segment, without speaker labels."
)


class GeminiError(RuntimeError):
    """Falla de la transcripción con Gemini (mensaje legible, nunca incluye la API key)."""


class CuotaAgotada(GeminiError):
    """HTTP 429 de cuota."""


class Presupuesto:
    """Cuenta las llamadas para cuidar la cuota (free tier: 20 requests/día y cada reintento cuenta)."""

    def __init__(self):
        self.generate = Counter()  # llamadas a generateContent por modelo (incluye reintentos)
        self.files = 0             # llamadas a la Files API (subida, estado y borrado)

    @property
    def total(self):
        return sum(self.generate.values())

    def resumen(self):
        por_modelo = ", ".join(f"{m}: {n}" for m, n in self.generate.items()) or "ninguna"
        return (f"Presupuesto Gemini: {self.total} llamada(s) a generateContent ({por_modelo}) y "
                f"{self.files} a la Files API. Free tier: {FREE_TIER_RPD} requests/día por modelo; "
                "cada reintento cuenta.")


@dataclass
class Trozo:
    path: Path
    inicio: float             # segundos absolutos dentro del audio original
    fin: float | None = None  # None si no se conoce

    @property
    def duracion(self):
        return None if self.fin is None else self.fin - self.inicio


@dataclass
class Resultado:
    segments: list = field(default_factory=list)  # [(inicio_s, fin_s, texto)] absolutos
    duracion: float | None = None
    fuente_duracion: str = ""
    modelos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    ok: bool = False
    verificacion: str = ""

    @property
    def lines(self):
        return format_lines(self.segments)


def _log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- formato y parseo

def fmt_ts(sec):
    """Segundos -> mm:ss (los minutos pueden pasar de 59, igual que fetch_transcripts.py)."""
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _segmento(obj):
    """Normaliza un objeto {start_sec, end_sec, text}; None si no sirve."""
    if not isinstance(obj, dict):
        return None
    start = _num(obj.get("start_sec"))
    text = " ".join(str(obj.get("text") or "").split())
    if start is None or start < 0 or not text:
        return None
    end = _num(obj.get("end_sec"))
    if end is None or end < start:
        end = start
    return {"start_sec": start, "end_sec": end, "text": text}


def _rescatar(t):
    """Objetos completos de un arreglo JSON truncado."""
    dec, objs = json.JSONDecoder(), []
    i = t.find("[") + 1
    if i == 0:
        return objs
    while True:
        while i < len(t) and t[i] in " \t\r\n,":
            i += 1
        if i >= len(t) or t[i] != "{":
            break
        try:
            obj, i = dec.raw_decode(t, i)
        except json.JSONDecodeError:
            break
        objs.append(obj)
    return objs


def parse_segments(texto):
    """Texto JSON de Gemini -> (segmentos normalizados, completo). Si viene truncado rescata lo completo."""
    t = (texto or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    if not t:
        return [], True
    try:
        data, completo = json.loads(t), True
    except json.JSONDecodeError:
        data, completo = _rescatar(t), False
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    segs = [s for s in map(_segmento, data if isinstance(data, list) else []) if s]
    return segs, completo


def merge_segments(trozos):
    """[(offset_s, [segmento JSON, ...]), ...] -> [(inicio_abs, fin_abs, texto)] ordenado.

    Suma el offset de cada trozo a sus timestamps (un trozo que empieza en 480 s convierte
    start_sec 5 en 485). Quita el duplicado exacto que a veces queda en la unión de dos trozos.
    """
    out = []
    for offset, segs in trozos:
        for s in segs:
            s = _segmento(s)
            if s:
                out.append((offset + s["start_sec"], offset + s["end_sec"], s["text"]))
    out.sort(key=lambda x: (x[0], x[1]))
    limpio = []
    for seg in out:
        if limpio and seg[2] == limpio[-1][2] and seg[0] - limpio[-1][0] <= 5:
            continue
        limpio.append(seg)
    return limpio


def format_lines(segs):
    return [f"[{fmt_ts(s)}] {t}" for s, _e, t in segs]


def to_lines(trozos):
    """[(offset_s, [segmento JSON, ...]), ...] -> ["[mm:ss] texto", ...] con los offsets sumados."""
    return format_lines(merge_segments(trozos))


def verificar(segs, duracion, fuente):
    """Primer timestamp cerca de 00:00 y último cerca de la duración real. Devuelve (ok, texto)."""
    if not segs:
        return False, "Verificación: AVISO, Gemini no devolvió segmentos."
    primero = segs[0][0]
    ultimo = max(e for _s, e, _t in segs)
    problemas = []
    if primero > TOL_INICIO_S:
        problemas.append(f"el primer timestamp es {fmt_ts(primero)} (se esperaba cerca de 00:00)")
    if duracion:
        tol = max(TOL_FIN_S, 0.03 * duracion)
        if ultimo < duracion - tol:
            problemas.append(f"el último timestamp ({fmt_ts(ultimo)}) queda lejos del final "
                             f"({fmt_ts(duracion)}): puede faltar audio")
        elif ultimo > duracion + 5:
            problemas.append(f"el último timestamp ({fmt_ts(ultimo)}) pasa la duración real "
                             f"({fmt_ts(duracion)}): timestamps corridos")
        dur_txt = f"duración real {fmt_ts(duracion)} ({fuente})"
    else:
        dur_txt = "duración desconocida (sin ffprobe ni metadata), no se pudo verificar el final"
    base = (f"Verificación: primer timestamp [{fmt_ts(primero)}], último [{fmt_ts(segs[-1][0])}] "
            f"(termina en {fmt_ts(ultimo)}), {dur_txt}")
    if problemas:
        return False, f"{base}. AVISO: {'; '.join(problemas)}. Revisa antes de usar el transcript."
    if not duracion:
        return False, f"{base}."
    return True, f"{base}: OK."


# ---------------------------------------------------------------- ffmpeg / ffprobe

def _run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def ffprobe_duration(path):
    """Duración en segundos con ffprobe, o None si no está instalado o falla."""
    if not shutil.which("ffprobe"):
        return None
    try:
        p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=120)
        return float(p.stdout.strip().splitlines()[0])
    except (ValueError, IndexError, OSError, subprocess.SubprocessError):
        return None


def _codec(src):
    """mp3 se copia tal cual; cualquier otro formato se re-encoda a mp3."""
    return ["-c", "copy"] if Path(src).suffix.lower() == ".mp3" else ["-c:a", "libmp3lame", "-q:a", "5"]


def cortar(src, segundos, carpeta, prefijo="trozo", base=0.0):
    """Corta src en trozos de `segundos` con ffmpeg. Tiempos absolutos = base + tiempo dentro de src."""
    carpeta = Path(carpeta)
    lista = carpeta / f"{prefijo}.csv"
    p = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-map", "0:a:0", "-vn",
              *_codec(src), "-f", "segment", "-segment_time", f"{segundos:g}", "-reset_timestamps", "1",
              "-segment_list", str(lista), "-segment_list_type", "csv",
              str(carpeta / f"{prefijo}_%03d.mp3")], timeout=1800)
    if p.returncode != 0 or not lista.exists():
        raise GeminiError(f"ffmpeg no pudo cortar el audio: {p.stderr.strip()[-300:]}")
    trozos = []
    for row in csv.reader(lista.read_text(encoding="utf-8").splitlines()):
        if len(row) >= 3:
            trozos.append(Trozo(carpeta / row[0], base + float(row[1]), base + float(row[2])))
    if not trozos:
        raise GeminiError("ffmpeg no generó trozos (¿el audio está vacío?)")
    return trozos


def recortar(src, desde, dst):
    """Copia de src desde el segundo `desde` hasta el final."""
    p = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{desde:.3f}", "-i", str(src),
              "-map", "0:a:0", "-vn", *_codec(src), str(dst)], timeout=900)
    if p.returncode != 0 or not Path(dst).exists():
        raise GeminiError(f"ffmpeg no pudo recortar el audio: {p.stderr.strip()[-300:]}")
    return Path(dst)


# ---------------------------------------------------------------- API REST de Gemini

def _mensaje(r):
    try:
        return " ".join(str(r.json()["error"]["message"]).split())[:300]
    except (ValueError, KeyError, TypeError):
        return " ".join(r.text.split())[:300]


def _retry_delay(r, default=60):
    try:
        for d in r.json()["error"].get("details", []):
            if "retryDelay" in d:
                return min(120, float(str(d["retryDelay"]).rstrip("s")) + 1)
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return default


class Cliente:
    def __init__(self, api_key, presupuesto, log):
        self.s = requests.Session()
        self.s.headers["x-goog-api-key"] = api_key  # en header, nunca en la URL (no sale en errores)
        self.p = presupuesto
        self.log = log

    def _http(self, method, url, modelo=None, reintentos=REINTENTOS, timeout=(30, 300), **kw):
        """Llamada con reintentos para 5xx y errores de red. Cuenta cada intento en el presupuesto."""
        err = ""
        for intento in range(reintentos + 1):
            if modelo:
                self.p.generate[modelo] += 1
            else:
                self.p.files += 1
            try:
                r = self.s.request(method, url, timeout=timeout, **kw)
            except requests.RequestException as e:
                r, err = None, f"error de red ({type(e).__name__})"
            if r is not None:
                if r.status_code < 400:
                    return r
                if r.status_code == 429:
                    # Límite por minuto: esperar y repetir. Cuota diaria: que el llamador cambie de modelo.
                    if "PerMinute" in r.text and intento < reintentos:
                        espera = _retry_delay(r)
                        self.log(f"  429 límite por minuto; espero {espera:.0f} s")
                        time.sleep(espera)
                        continue
                    raise CuotaAgotada(f"429 cuota agotada{' en ' + modelo if modelo else ''}: {_mensaje(r)}")
                if r.status_code < 500:
                    raise GeminiError(f"HTTP {r.status_code}: {_mensaje(r)}")
                err = f"HTTP {r.status_code}: {_mensaje(r)}"
            if intento < reintentos:
                espera = BACKOFF_S * (intento + 1)
                self.log(f"  {err[:160]}; reintento {intento + 1}/{reintentos} en {espera} s")
                time.sleep(espera)
        raise GeminiError(f"falló después de {reintentos} reintentos: {err}")

    @staticmethod
    def _json(r):
        try:
            return r.json()
        except ValueError:
            raise GeminiError(f"respuesta no JSON de Gemini: {r.text[:200]}") from None

    def subir(self, path, mime):
        """Sube un archivo a la Files API con el protocolo resumable y espera a que quede ACTIVE."""
        data = Path(path).read_bytes()
        r = self._http("POST", UPLOAD_URL, timeout=(30, 120), json={"file": {"display_name": Path(path).name}},
                       headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                                "X-Goog-Upload-Header-Content-Length": str(len(data)),
                                "X-Goog-Upload-Header-Content-Type": mime})
        upload_url = r.headers.get("x-goog-upload-url")
        if not upload_url:
            raise GeminiError("la Files API no devolvió la URL de subida (x-goog-upload-url)")
        r = self._http("POST", upload_url, timeout=(30, 900), data=data,
                       headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"})
        f = self._json(r).get("file") or {}
        for _ in range(60):
            estado = f.get("state")
            if estado in (None, "ACTIVE"):
                if not f.get("uri"):
                    raise GeminiError("la Files API no devolvió el uri del archivo")
                f.setdefault("mimeType", mime)
                return f
            if estado == "FAILED":
                raise GeminiError("Gemini no pudo procesar el archivo subido (state FAILED)")
            time.sleep(2)
            f = self._json(self._http("GET", f"{API}/{f['name']}", timeout=(30, 60)))
        raise GeminiError("el archivo subido sigue en PROCESSING después de 2 minutos")

    def borrar(self, archivo):
        """Borra el archivo de la Files API (si falla no importa: expira solo a las 48 h)."""
        try:
            self._http("DELETE", f"{API}/{archivo['name']}", reintentos=0, timeout=(30, 60))
        except (GeminiError, KeyError):
            pass

    def generar(self, modelo, archivo, prompt):
        """generateContent con responseSchema. Devuelve (texto, finishReason)."""
        modelo = modelo.removeprefix("models/")
        body = {
            "contents": [{"role": "user", "parts": [
                {"fileData": {"mimeType": archivo["mimeType"], "fileUri": archivo["uri"]}},
                {"text": prompt},
            ]}],
            # Sin thinkingConfig a propósito: el thinking es el que hace la transcripción real.
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
            },
        }
        r = self._http("POST", f"{API}/models/{modelo}:generateContent", modelo=modelo, timeout=(30, 900),
                       json=body)
        data = self._json(r)
        cands = data.get("candidates") or []
        if not cands:
            motivo = (data.get("promptFeedback") or {}).get("blockReason") or "respuesta vacía"
            raise GeminiError(f"Gemini no devolvió candidatos ({motivo})")
        c = cands[0]
        texto = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts") or []
                        if not p.get("thought"))
        razon = c.get("finishReason") or ""
        if not texto.strip() and razon not in ("STOP", "MAX_TOKENS"):
            raise GeminiError(f"Gemini no devolvió texto (finishReason {razon or 'desconocido'})")
        return texto, razon


# ---------------------------------------------------------------- transcripción

def build_prompt(lang, context, duracion):
    bounds = ""
    if duracion:
        bounds = f" (it lasts about {duracion:.0f} seconds, so every value must be between 0 and {duracion:.0f})"
    prompt = PROMPT.format(language=LANGS.get(lang, lang), bounds=bounds)
    if context:
        prompt += f"\nContext to spell proper names correctly (teams, players, people): {context}"
    return prompt


def _mime(path):
    suf = Path(path).suffix.lower()
    return MIMES.get(suf) or mimetypes.guess_type(str(path))[0] or "audio/mp3"


def _transcribir_trozo(cliente, t, lang, context, modelo, fallback):
    """Sube el trozo, pide la transcripción (cambia a fallback si hay 429) y lo borra."""
    archivo = cliente.subir(t.path, _mime(t.path))
    try:
        prompt = build_prompt(lang, context, t.duracion)
        try:
            texto, razon = cliente.generar(modelo, archivo, prompt)
        except CuotaAgotada as e:
            if not fallback or fallback == modelo:
                raise
            cliente.log(f"  {str(e)[:160]}")
            cliente.log(f"  cambio a {fallback} (cuota independiente)")
            modelo = fallback
            texto, razon = cliente.generar(modelo, archivo, prompt)
    finally:
        cliente.borrar(archivo)
    segs, completo = parse_segments(texto)
    return segs, completo and razon != "MAX_TOKENS", modelo


def transcribe_audio(audio, lang=DEFAULT_LANG, model=DEFAULT_MODEL, fallback_model=DEFAULT_FALLBACK,
                     chunk=DEFAULT_CHUNK, context=None, duration_hint=None, presupuesto=None, log=None,
                     api_key=None):
    """Transcribe `audio` con Gemini y devuelve un Resultado (segments absolutos, verificación, avisos).

    duration_hint: duración conocida por metadata (yt-dlp); se usa si no hay ffprobe.
    presupuesto: Presupuesto compartido para contar llamadas entre varios audios (se actualiza aunque falle).
    Lanza GeminiError si falta la API key, ffmpeg (con chunk > 0) o si la API falla sin remedio.
    """
    log = log or _log
    presupuesto = presupuesto if presupuesto is not None else Presupuesto()
    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise GeminiError("GEMINI_API_KEY no está definida (se obtiene en https://aistudio.google.com/apikey)")
    audio = Path(audio)
    if not audio.is_file():
        raise GeminiError(f"no existe el audio {audio}")
    hay_ffmpeg = shutil.which("ffmpeg") is not None
    if chunk and chunk > 0 and not hay_ffmpeg:
        raise GeminiError("ffmpeg no está en el PATH y hace falta para cortar el audio en trozos "
                          "(winget install Gyan.FFmpeg); con --chunk 0 se manda el audio completo")

    cliente = Cliente(key, presupuesto, log)
    res = Resultado()
    dur, fuente = ffprobe_duration(audio), "ffprobe"
    if not dur and duration_hint:
        dur, fuente = float(duration_hint), "metadata"

    with tempfile.TemporaryDirectory(prefix="mazopicks_gemini_") as tmp:
        tmp = Path(tmp)
        if chunk and chunk > 0:
            trozos = cortar(audio, chunk, tmp)
            if not dur and trozos[-1].fin:
                dur, fuente = trozos[-1].fin, "suma de trozos"
        else:
            trozos = [Trozo(audio, 0.0, dur)]
        pendientes = deque(t for t in trozos if t.duracion is None or t.duracion >= MIN_TROZO_S)
        corte = f"de hasta {chunk:g} s" if chunk and chunk > 0 else "(audio completo, sin cortar)"
        log(f"{audio.name}: {len(pendientes)} trozo(s) {corte}, modelo {model}")

        resultados, modelo, n = [], model, 0
        while pendientes:
            t = pendientes.popleft()
            n += 1
            rango = f"[{fmt_ts(t.inicio)}-{fmt_ts(t.fin) if t.fin is not None else '?'}]"
            segs, completo, modelo = _transcribir_trozo(cliente, t, lang, context, modelo, fallback_model)
            if modelo not in res.modelos:
                res.modelos.append(modelo)
            dur_t = t.duracion
            if dur_t and any(s["start_sec"] > dur_t + 5 for s in segs):
                res.avisos.append(f"trozo {rango}: Gemini devolvió timestamps más allá del trozo")
            if completo:
                resultados.append((t.inicio, segs))
                log(f"  trozo {n} {rango}: {len(segs)} segmentos ({modelo})")
                continue
            # Respuesta truncada (maxOutputTokens): cortar con ffmpeg, nunca pedir que agrupe turnos.
            ultimo = max((s["end_sec"] for s in segs), default=0.0)
            if hay_ffmpeg and dur_t and segs and ultimo >= 10 and dur_t - ultimo > 5:
                resultados.append((t.inicio, segs))
                resto = recortar(t.path, ultimo, tmp / f"resto_{n:03d}.mp3")
                pendientes.appendleft(Trozo(resto, t.inicio + ultimo, t.fin))
                log(f"  trozo {n} {rango}: truncado; rescaté {len(segs)} segmentos hasta "
                    f"{fmt_ts(t.inicio + ultimo)} y corto el resto con ffmpeg")
            elif hay_ffmpeg and dur_t and dur_t > SPLIT_TRUNCADO + 10:
                subs = cortar(t.path, SPLIT_TRUNCADO, tmp, f"sub_{n:03d}", base=t.inicio)
                pendientes.extendleft(reversed([s for s in subs if s.duracion >= MIN_TROZO_S]))
                log(f"  trozo {n} {rango}: truncado sin segmentos útiles; lo parto en trozos de "
                    f"{SPLIT_TRUNCADO} s")
            else:
                resultados.append((t.inicio, segs))
                res.avisos.append(f"trozo {rango}: respuesta truncada que no se pudo partir más "
                                  f"({len(segs)} segmentos rescatados)")
                log(f"  trozo {n} {rango}: truncado y no se puede partir más; uso {len(segs)} segmentos")

    res.segments = merge_segments(resultados)
    res.duracion, res.fuente_duracion = dur, (fuente if dur else "")
    res.ok, res.verificacion = verificar(res.segments, dur, fuente)
    if res.avisos:
        res.ok = False
    return res


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")  # consola de Windows con cp1252
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Transcribe un audio con Gemini (API REST) a líneas [mm:ss] texto.")
    ap.add_argument("--audio", required=True, help="archivo de audio (mp3 recomendado)")
    ap.add_argument("--out", required=True, help="archivo .txt de salida")
    ap.add_argument("--lang", default=DEFAULT_LANG, help="idioma esperado del audio (default en)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"modelo (default {DEFAULT_MODEL})")
    ap.add_argument("--fallback-model", default=DEFAULT_FALLBACK,
                    help=f"modelo si hay 429 de cuota (default {DEFAULT_FALLBACK}); vacío para no cambiar")
    ap.add_argument("--chunk", type=float, default=DEFAULT_CHUNK,
                    help=f"segundos por trozo (default {DEFAULT_CHUNK}; 90 para banter rápido; 0 = sin cortar)")
    ap.add_argument("--context", default="", help="nombres de equipos y jugadores para mejorar la ortografía")
    a = ap.parse_args(argv)

    pres = Presupuesto()
    try:
        res = transcribe_audio(a.audio, lang=a.lang, model=a.model, fallback_model=a.fallback_model,
                               chunk=a.chunk, context=a.context or None, presupuesto=pres)
    except GeminiError as e:
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        print(pres.resumen(), flush=True)
        return 1
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    head = [f"# audio: {Path(a.audio).name}", "# transcript_method: gemini",
            f"# gemini_model: {', '.join(res.modelos)}", ""]
    out.write_text("\n".join(head + res.lines) + "\n", encoding="utf-8")
    print(f"{len(res.segments)} segmentos -> {out}", flush=True)
    for aviso in res.avisos:
        print(f"AVISO: {aviso}", flush=True)
    print(res.verificacion, flush=True)
    print(pres.resumen(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
