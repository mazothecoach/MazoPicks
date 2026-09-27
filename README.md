# MazoPicks

Proyecto personal para la temporada NFL 2026:

- Baja los videos de picks de los canales de YouTube que sigo (hoy The Sauce Picks, @KyleKirms), los transcribe y Claude extrae los picks e insights por semana NFL.
- Compara el momio de cada pick en Playdoit (americanos) y Draftea (decimales).
- Trackea mis boletos (capturas en Google Drive) y mide en qué mercados me va bien o mal.
- Lleva el bankroll 2026 con ledger semanal depósito/retiro y stop loss: si el neto acumulado llega a **-10,000 MXN**, se deja de apostar el resto de la temporada.
- Publica todo en un sitio estático (GitHub Pages desde `/docs` en `main`).

Solo para análisis personal. No es asesoría de apuestas. Las reglas completas y los esquemas están en [CLAUDE.md](CLAUDE.md).

## Estructura

```
MazoPicks/
  CLAUDE.md                  especificación y esquemas para Claude
  channels.json              canales a seguir (lo único que se edita para agregar uno)
  requirements.txt
  weekly_prompt.md           prompt de la corrida semanal (claude -p)
  run_weekly.ps1             corrida semanal en Windows (Programador de tareas)
  .github/workflows/         build-site.yml y grade-picks.yml
  scripts/                   scripts de Python (ver abajo)
  data/
    config.json              temporada, kickoff, stop loss, casas, show_amounts
    bankroll_2026.json       ledger semanal (fuente de verdad del stop loss)
    bankroll_2026_status.json    generado por bankroll.py
    my_bets.json             mis boletos extraídos de capturas
    my_bets_analysis.json    generado por analyze_my_bets.py
    picks/2026-W03.json      picks e insights por semana
    odds/2026-W03.json       momios por pick en cada casa
    transcripts/{video_id}.txt
    history/                 bankroll 2024 y 2025 + análisis
    videos_processed.json    videos ya procesados (evita duplicar)
    screenshots_processed.json   capturas ya extraídas
  docs/                      sitio (docs/data lo genera build_site.py, no se edita a mano)
  logs/                      run_{fecha}.log (local, ignorado) y {fecha}.md (resumen)
```

## Instalación en Windows

Requisitos: Python 3.11+, [Git for Windows](https://git-scm.com/download/win) y Claude Code instalado (`claude --version`) con sesión iniciada (corre `claude` una vez a mano).

```powershell
git clone https://github.com/mazothecoach/MazoPicks.git
cd MazoPicks
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# ffmpeg y ffprobe: cortan el audio en trozos para Gemini y miden su duración real (Whisper también los usa)
winget install Gyan.FFmpeg

# Recomendado: transcripción con Gemini para videos sin subtítulos (sin SDK, usa requests)
# Key gratis en https://aistudio.google.com/apikey. Queda como variable de usuario: abre una terminal nueva después.
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "PEGA_TU_KEY_AQUI", "User")

# Opcional: transcripción local con Whisper (último recurso)
pip install faster-whisper
```

Si PowerShell no deja activar el venv: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Si yt-dlp avisa que le falta un runtime de JavaScript para YouTube: `winget install DenoLand.Deno`.
Cookies de YouTube: en la compu de Mazo ya están configuradas (`%USERPROFILE%\.yt-dlp\cookies.txt`, y `%APPDATA%\yt-dlp\config` ya apunta ahí), así que yt-dlp no necesita `--cookies`. Si YouTube pide "Sign in to confirm you're not a bot", las cookies expiraron: re-expórtalas con la extensión de Chrome "Get cookies.txt LOCALLY" y sobrescribe el archivo.
La API key de Gemini es como una contraseña: no la pegues en el repo (es público) ni en chats.

## Scripts

Todos se corren desde la raíz del repo con el venv activo.

```powershell
# Semana NFL de una fecha (martes a lunes; "Week N" en el título manda)
python scripts/nfl_week.py
python scripts/nfl_week.py 2026-09-27 "Week 3 NFL Picks with Kyle Kirms"

# Videos nuevos de los canales -> data/videos_new.json
python scripts/fetch_videos.py                     # últimos 8 días
python scripts/fetch_videos.py --days 3 --max 10
python scripts/fetch_videos.py --ids 4o0fpns6Gm0,gM-02rLbR9w --force
$env:YTDLP_EXTRA_ARGS = "--cookies-from-browser chrome"   # si YouTube bloquea

# Transcripciones -> data/transcripts/{video_id}.txt (API, subtítulos, Gemini, Whisper)
python -u scripts/fetch_transcripts.py
python -u scripts/fetch_transcripts.py 4o0fpns6Gm0 NRYYHPXEjbc
$env:WHISPER_MODEL = "small"                       # default "base"

# Transcribir un audio suelto con Gemini (ver "Transcripción")
python -u scripts/transcribe_gemini.py --audio x.mp3 --out data/transcripts/ID.txt --lang en

# Calificar picks con marcadores de ESPN (moneyline, spread, total)
python scripts/grade_picks.py
python scripts/grade_picks.py 2026-W03 --dry

# Comparar momios Playdoit vs Draftea
python scripts/compare_odds.py 2026-W03

# Bankroll 2026 y stop loss
python scripts/bankroll.py
python scripts/bankroll.py set --week 3 --deposito 1500 --retiro 400

# Análisis de mis boletos e historial 2024 vs 2025
python scripts/analyze_my_bets.py
python scripts/analyze_history.py

# Regenerar docs/data (corre también bankroll, análisis y compare_odds)
python scripts/build_site.py
```

## Transcripción

`fetch_transcripts.py` prueba en este orden y se queda con el primero que funcione (queda en `# transcript_method:` del .txt):

1. `youtube-transcript-api` (subtítulos de YouTube, en y es).
2. `yt-dlp --write-auto-subs` (subtítulos automáticos).
3. `gemini`, solo si `GEMINI_API_KEY` está definida: baja el audio a mp3 con yt-dlp y lo transcribe con `scripts/transcribe_gemini.py`.
4. Whisper local, si está instalado.

Gemini es el camino confiable del método "Cómo Claude ve videos" (probado en 6 episodios):

- Requiere ffmpeg en el PATH: el audio se corta en trozos de 480 s (`--chunk`) y cada trozo es una llamada. Si una respuesta sale truncada, el script rescata lo completo y corta el resto con ffmpeg; para banter muy rápido usa `--chunk 90`.
- Cuota: el free tier de gemini-2.5-flash son **20 requests/día** y cada reintento cuenta (un video de 30 min son unas 4 llamadas). Un 503 se reintenta con backoff de 20 s; un 429 cambia solo a gemini-3.5-flash-lite (cuota aparte). Al final imprime cuántas llamadas hizo.
- Verificación: imprime el primer y el último timestamp contra la duración real (ffprobe); si dice AVISO, revisa el transcript antes de extraer picks.
- Corre siempre con `python -u` para no perder la salida si el proceso muere.

Audio suelto (por ejemplo, para rehacer un video a mano):

```powershell
yt-dlp -f "bestaudio" -x --audio-format mp3 --audio-quality 5 --force-overwrites -o "x.%(ext)s" "https://www.youtube.com/watch?v=ID"
python -u scripts/transcribe_gemini.py --audio x.mp3 --out data/transcripts/ID.txt --lang en
python -u scripts/transcribe_gemini.py --audio x.mp3 --out data/transcripts/ID.txt --lang en --context "Jordan Love, Bijan Robinson"
```

Con `-o x.mp3` el yt-dlp actual deja `x.mp3.mp3`; por eso aquí va `-o "x.%(ext)s"`. El .txt que escribe `transcribe_gemini.py` lleva un encabezado mínimo (`# transcript_method: gemini`); `fetch_transcripts.py` pone el completo (título, canal, semana).

## Flujo semanal

| Cuándo (CDMX) | Qué pasa | Dónde |
|---|---|---|
| Jueves a domingo | Kyle publica videos (TNF, domingo, en vivo) | YouTube |
| Sábado 06:45 y martes 06:45 | Califica picks con ESPN y reconstruye el sitio | GitHub Actions |
| Sábado 08:00 y domingo 09:00 | `run_weekly.ps1`: videos, transcripciones, picks, calificación, sitio, commit y push | Compu Windows |
| Antes de apostar | Capturas de momios de los picks en Playdoit y Draftea a Drive | Celular + Claude Code web |
| Después de apostar | Capturas de boletos a Drive y extracción a `my_bets.json` | Celular + Claude Code web |
| Lunes o martes | Depósito y retiro de la semana en el ledger | Local o Claude Code web |

La corrida semanal es idempotente: los videos ya marcados en `data/videos_processed.json` no se vuelven a procesar, por eso correr sábado y domingo no duplica picks. El detalle de cada paso está en [weekly_prompt.md](weekly_prompt.md).

Para correrla a mano: `.\run_weekly.ps1`.

## Capturas de boletos (Google Drive)

Carpetas (privadas, no las compartas con "cualquiera con el enlace"):

- [MazoPicks](https://drive.google.com/drive/folders/1GOR9QrpLpDB3vb78JRK0sS2SPkL_GJ0L)
- [MazoPicks/capturas_boletos](https://drive.google.com/drive/folders/1GQqt5mmUYAUpNsoF4nJCurn4_L-uUnlr): boletos de Playdoit y Draftea.
- [MazoPicks/capturas_momios](https://drive.google.com/drive/folders/1b668Kyl-iCDSTewqbgz9EFVtnoOM7jJH): momios de un pick en cada casa.

Formatos: **PNG o JPEG**. HEIC no se puede leer (las capturas de pantalla del iPhone ya son PNG; si subes fotos, exporta a JPEG o usa Ajustes > Cámara > Formatos > Más compatible). Captura el boleto expandido para que se vean las legs.

Para extraerlas, abre una sesión de Claude Code web sobre este repo con el conector de Google Drive y pide algo como:

```
Lee las capturas nuevas de Drive MazoPicks/capturas_boletos (las que no estén en
data/screenshots_processed.json), extráelas a data/my_bets.json según el _schema,
muéstrame la tabla resumen para validar, márcalas en screenshots_processed.json,
corre analyze_my_bets.py y build_site.py, y haz commit y push.
```

Claude deduplica por `ticket_id`, deja `validated: false` hasta que confirmes la tabla y nunca inventa legs ni momios (si algo no se lee, `null` y una nota).

## Momios (data/odds)

1. Abre el pick en Playdoit y en Draftea y toma captura donde se vea el partido, el mercado y el momio.
2. Súbelas a `capturas_momios` (ayuda nombrarlas tipo `W03_ATL-GB_playdoit.png`).
3. En Claude Code web pide: "extrae las capturas nuevas de capturas_momios a data/odds/2026-W03.json".

También se pueden capturar a mano en `data/odds/{season}-W{nn}.json` (el `pick_id` sale de `data/picks`):

```json
"entries": [
  {"pick_id": "4o0fpns6Gm0-01", "book": "playdoit", "odds_american": -110, "captured_at": "2026-09-27T10:15", "source": "captura W03_ATL-GB_playdoit.png"},
  {"pick_id": "4o0fpns6Gm0-01", "book": "draftea",  "odds_decimal": 1.95,  "captured_at": "2026-09-27T10:17", "source": "manual"}
]
```

Después `python scripts/compare_odds.py 2026-W03` (o `build_site.py`, que ya lo corre) llena `comparison` con la mejor casa, diferencia % y probabilidad implícita. Solo se registran momios vistos en la casa.

## Bankroll 2026 (ledger)

Mismo modelo que el Excel 2024/25: una fila por semana con depósito y retiro; `neto = retiro - deposito`. Al cierre de cada semana (lunes):

```powershell
python scripts/bankroll.py set --week 3 --deposito 1500 --retiro 400
python scripts/bankroll.py        # [ACTIVO / verde] neto ... | restante ...
```

`--week` es el `idx` de `data/bankroll_2026.json`: 1 a 18 temporada regular, 19 Wild Card, 20 Divisional, 21 Conference, 22 Super Bowl. Niveles: verde hasta -5,000, amarillo hasta -8,000, rojo hasta -10,000 y DETENIDO al llegar a -10,000 MXN. Después haz commit y push de `data/bankroll_2026.json` (Actions reconstruye el sitio).

## Agregar un canal

Solo se edita `channels.json`; no hay que tocar código:

```json
{
  "name": "Nombre del canal",
  "handle": "@handle",
  "url": "https://www.youtube.com/@handle",
  "league": "NFL",
  "title_keywords": ["week", "picks", "nfl"],
  "active": true,
  "notes": "Cuándo publica y qué tipo de videos.",
  "known_videos": []
}
```

Para pausar un canal sin borrarlo: `"active": false`.

## Activar GitHub Pages

1. GitHub > mazothecoach/MazoPicks > **Settings > Pages**.
2. Source: **Deploy from a branch**. Branch: **main**, carpeta **/docs**. Save.
3. En uno o dos minutos queda en https://mazothecoach.github.io/MazoPicks/

## Privacidad

El repo es **público**: cualquiera puede ver `data/` completo (boletos, montos, ledger, historial) aunque el sitio los oculte.

- `data/config.json` > `site.show_amounts: false` hace que `build_site.py` publique los montos MXN como "oculto" y el sitio muestre solo ROI y porcentajes. Esto afecta solo a `docs/data`, no a `data/`.
- Para privacidad real el repo tiene que ser privado, y GitHub Pages en repos privados requiere plan de pago (GitHub Pro).
- Las capturas se quedan en Drive; no se suben al repo.

## Automatización

YouTube y ESPN están bloqueados desde la nube de Claude, así que el trabajo se reparte:

**Local (Programador de tareas de Windows).** `run_weekly.ps1` activa `.venv`, hace `git pull`, corre `claude -p` con `weekly_prompt.md` y hace push si quedó algo pendiente. Salida completa en `logs/run_{fecha}.log`; Claude escribe el resumen en `logs/{fecha}.md`. Las tareas se registran con el bloque comentado al inicio de `run_weekly.ps1` (sábado 08:00 y domingo 09:00, "ejecutar tan pronto como sea posible si se omitió" y "activar el equipo"). Confirma los flags con `claude --help` antes de programarlas.

**GitHub Actions (nube).**

- `build-site.yml`: en cada push a `main` que toque `data/**`, `scripts/**` o `channels.json` corre `build_site.py` y, si `docs/data` cambió, hace commit `site: rebuild docs/data [skip ci]`.
- `grade-picks.yml`: sábado y martes 12:45 UTC (06:45 CDMX) corre `grade_picks.py` y `build_site.py` y hace commit `grade: picks calificados [skip ci]`.
- Ambos se pueden correr a mano en la pestaña **Actions > Run workflow**.
- Si el push de Actions falla con 403: Settings > Actions > General > Workflow permissions > Read and write.
- GitHub pausa los cron de repos sin actividad en 60 días; se reactivan desde la pestaña Actions.
