# MazoPicks · CLAUDE.md

Contexto y especificación para Claude Code. Léelo completo antes de hacer cualquier cosa.
Todo el sitio y los textos van en español. Nunca uses el carácter raya (em dash, guion largo) en ningún texto, ni del sitio ni de los mensajes.

## 0. Reglas de modelos y delegación (del usuario, aplican a toda sesión)

Never do the work yourself.
Always dispatch a sub-agent.
Don't always use Fable.
Use Opus 5.5 for easier tasks.

### Model routing
- Fable 5.1: architecture, hard bugs, review
- Opus 5.5: edits, tests, docs, refactors
- Haiku 4.5: lookups and summaries
- Pass model on every Agent call

### Delegation
- One sub-agent per task, plan first
- Run independent sub-agents in parallel
- Read the report, never the files

## 1. Objetivo

Sitio en GitHub Pages (repo público mazothecoach/MazoPicks, carpeta /docs en main) que:

1. Cada sábado en la mañana (y domingo, porque The Sauce sube el video de domingo el sábado en la noche) baje los videos nuevos de picks NFL de los canales que sigo, los transcriba, extraiga los picks y publique una pestaña por semana NFL.
2. Compare el momio de cada pick en Draftea y Playdoit (donde apuesto) y marque la mejor casa.
3. Trackee mis apuestas (capturas de boletos en Drive), qué mercados son los mejores de mi lado, y qué boletos siguieron picks de The Sauce vs ideas propias.
4. Lleve el bankroll 2026 con el mismo modelo de mi Excel 2024/25 (ledger semanal depósito/retiro) y aplique el stop loss: si el neto acumulado llega a -10,000 MXN, se deja de apostar el resto de la temporada.
5. Cruce todo: qué picks del canal caen en los tipos de apuesta donde a mí me va bien o mal, y los mejores insights de cada video.

## 2. Sobre mí (usuario)

- Mazo, Senior Data Analyst en México (America/Mexico_City). Ingeniero industrial. Prefiero decisiones basadas en datos, análisis comparativo y soluciones reutilizables y automatizadas. Prefiero Python que corra local.
- Apuesto NFL, sobre todo parlays y SGP con props de jugador (TDs, yardas, pases completados) y moneyline, incluyendo 1a mitad.
- Casas: Playdoit (playdoit.mx, momios americanos, montos MXN) y Draftea (draftea.com, momios decimales tipo 1.57x, tickets "TKT_...", apuestas gratis). Si una captura no permite identificar la casa, etiqueta book: "app_decimal" y book_confidence: "inferido".
- Historial: 2024 cerré +13,410.85 MXN. 2025 cerré -7,843 MXN y dejé de apostar después de la Week 11 por pasarme del presupuesto. Detalle en data/history/.
- Lecciones aprendidas que ya tengo escritas: no apostar en pretemporada ni las primeras dos semanas; mid season es el sweetspot; no apostar si no vi los juegos una semana antes; no apostar muy cerca de los juegos con prisa.
- Etiqueta claramente lo no verificado o especulativo ("No verificado", "Inferido del audio"). Nunca presentes como hecho algo que no esté confirmado. Nunca inventes momios.

## 3. Arquitectura (híbrida)

YouTube y ESPN están bloqueados desde la nube de Claude Code (web). Por eso:

| Dónde | Qué corre |
|---|---|
| Compu Windows (Programador de tareas, sábado 08:00 y domingo 09:00) | run_weekly.ps1: git pull, fetch_videos.py, fetch_transcripts.py, Claude extrae picks de las transcripciones, grade_picks.py, build_site.py, commit y push |
| GitHub Actions | build-site.yml (reconstruye docs/data en cada push a main) y grade-picks.yml (califica picks con ESPN martes y sábado) |
| Claude Code web + conector de Google Drive | Lee las capturas de boletos y momios que subo a Drive y las extrae a data/my_bets.json y data/odds/ |

La extracción de picks desde la transcripción la hace Claude Code leyendo el .txt, no una API externa. No se necesita API key (GEMINI_API_KEY es opcional y solo sirve para transcribir videos sin subtítulos, ver 4.3).

```
MazoPicks/
├── CLAUDE.md
├── README.md
├── channels.json                # canales a seguir (editable, sin cambios de código)
├── requirements.txt
├── run_weekly.ps1               # lo corre el Programador de tareas
├── weekly_prompt.md             # prompt para `claude -p`
├── .github/workflows/           # build-site.yml, grade-picks.yml
├── scripts/
│   ├── nfl_week.py              # fecha -> temporada y semana NFL
│   ├── fetch_videos.py          # videos nuevos por canal (yt-dlp)
│   ├── fetch_transcripts.py     # transcripción con fallback (API, subs, gemini, whisper)
│   ├── transcribe_gemini.py     # audio -> "[mm:ss] texto" con la API REST de Gemini (trozos con ffmpeg)
│   ├── grade_picks.py           # califica picks con ESPN
│   ├── analyze_my_bets.py       # métricas de mis apuestas
│   ├── analyze_history.py       # métricas 2024 vs 2025
│   ├── bankroll.py              # ledger 2026 + stop loss
│   ├── compare_odds.py          # Draftea vs Playdoit por pick
│   └── build_site.py            # genera docs/data desde data/
├── data/
│   ├── config.json              # temporada, kickoff, stop loss, casas, show_amounts
│   ├── history/                 # bankroll_2024.json, bankroll_2025.json, distribucion_semanal.json, analysis.json
│   ├── bankroll_2026.json       # ledger semanal (fuente de verdad del stop loss)
│   ├── bankroll_2026_status.json (generado)
│   ├── my_bets.json             # mis boletos (extraídos de capturas)
│   ├── my_bets_analysis.json    (generado)
│   ├── screenshots_processed.json
│   ├── videos_processed.json
│   ├── transcripts/{video_id}.txt
│   ├── picks/{season}-W{nn}.json
│   └── odds/{season}-W{nn}.json
├── docs/                        # GitHub Pages sirve desde /docs en main
│   ├── index.html, assets/app.js, assets/style.css
│   └── data/                    # copias JSON que consume el front (generado por build_site.py)
└── logs/
```

## 4. Fuentes de datos

### 4.1 Canales (channels.json)
The Sauce Picks (@KyleKirms). Publica varios videos por semana NFL: jueves (TNF), sábado noche o domingo (picks del domingo) y shows en vivo. Todos se agrupan en la misma semana. Para agregar un canal solo se edita channels.json.

### 4.2 Descubrimiento de videos (fetch_videos.py)
yt-dlp --flat-playlist sobre {url}/videos, filtra por title_keywords, últimos 8 días, duración >= 90 s (excluye Shorts) y no procesados (data/videos_processed.json). Si YouTube bloquea, usar YTDLP_EXTRA_ARGS="--cookies-from-browser chrome".

### 4.3 Transcripción (fetch_transcripts.py), en este orden
1. youtube-transcript-api (en, es)
2. yt-dlp --write-auto-subs (VTT limpiado)
3. gemini, solo si GEMINI_API_KEY está definida: baja el audio con `yt-dlp -f "bestaudio" -x --audio-format mp3 --audio-quality 5 --force-overwrites -o {id}.mp3 URL` y lo transcribe con scripts/transcribe_gemini.py (API REST de Gemini sin SDK, trozos de 480 s con ffmpeg, idioma en). Con el yt-dlp actual ese comando deja {id}.mp3.mp3 (baja el stream webm como {id}.mp3 y lo convierte); el script acepta los dos nombres. Gasta cuota: fetch_transcripts.py imprime cuántas llamadas hizo.
4. Whisper local (faster-whisper o whisper CLI; modelo en WHISPER_MODEL)

Salida: data/transcripts/{video_id}.txt con encabezado (título, canal, fecha, url, semana, método) y líneas "[mm:ss] texto".

Lecciones del documento "Cómo Claude ve videos" (método de Mazo, probado en 6 episodios):
- Cookies de YouTube ya configuradas en la compu de Mazo: %USERPROFILE%\.yt-dlp\cookies.txt y el config de yt-dlp (%APPDATA%\yt-dlp\config) ya apunta ahí, así que no hace falta pasar --cookies. Si YouTube pide "Sign in to confirm you're not a bot", las cookies expiraron: re-exportarlas (extensión "Get cookies.txt LOCALLY") y sobrescribir el archivo.
- La metadata (`yt-dlp --no-download --dump-single-json URL`) va en su propio comando; combinarla con la descarga del audio causa timeouts. Si yt-dlp parece colgado en [ExtractAudio], revisar si el mp3 ya existe antes de matarlo.
- No apagar el thinking de Gemini: con thinkingBudget=0 degenera en basura repetida.
- Timestamps como número (start_sec, end_sec), nunca string HH:MM:SS; el formato [mm:ss] lo pone el script.
- maxOutputTokens 65536. Si la respuesta se trunca, cortar el mp3 en trozos con ffmpeg (~90 s para banter rápido, `--chunk 90`); nunca pedirle a Gemini que agrupe turnos ni que agrupe y lleve el tiempo en la misma pasada.
- Cuota: el free tier de gemini-2.5-flash son 20 requests/día reales y cada reintento cuenta. 503: reintentar con backoff de 20 s. 429: fallback a gemini-3.5-flash-lite (cuota independiente; gemini-2.5-flash-lite ya no existe).
- Siempre `python -u`: sin eso, un proceso que muere en background se lleva toda la salida.
- Verificar antes de usar el transcript: primer timestamp cerca de 00:00 y último cerca de la duración real (ffprobe o metadata). transcribe_gemini.py lo imprime; si dice AVISO, revisar antes de extraer picks.
- Los labels de speaker no son confiables: no atribuir un pick a alguien solo por quién parece hablar.
- No usar el MCP claude-video-vision: es poco confiable (timeouts, captions ausentes) y no es parte del flujo. Para ver un momento puntual basta un frame: `ffmpeg -ss <segundos> -i <video> -frames:v 1 frame.png`.

### 4.4 Semana NFL (nfl_week.py)
Temporada 2026: kickoff miércoles 9 de septiembre de 2026 (SEA vs NE), verificado en línea el 27 sep 2026. La semana NFL va de martes a lunes; Week 1 = 8 a 14 sep. Si el título del video dice "Week N", ese número manda sobre el cálculo por fecha.

## 5. Esquemas

### 5.1 Pick de canal (data/picks/2026-W03.json)
```json
{
  "season": 2026, "week": 3, "generated_at": "2026-09-26T08:00:00-06:00", "status": "ok",
  "sources": [{"channel": "The Sauce Picks", "video_id": "4o0fpns6Gm0", "title": "...", "url": "...", "published": "2026-09-26", "transcript_method": "youtube-transcript-api"}],
  "picks": [{
    "id": "4o0fpns6Gm0-01", "channel": "The Sauce Picks", "video_id": "4o0fpns6Gm0", "game": "ATL @ GB", "kickoff": "2026-09-24",
    "market": "player_prop", "category": "pass_comp", "selection": "Jordan Love over 20.5 completions",
    "line": 20.5, "odds_american": -110, "odds_decimal": 1.91,
    "confidence": "alta", "is_lock": false, "units": null,
    "reasoning": "Resumen de 1 a 2 frases del porqué, en español.", "timestamp": "12:34",
    "verified": false, "result": null, "result_manual": null,
    "confidence_note": "Inferido del audio", "also_in": [], "notes": null
  }],
  "insights": ["3 a 6 bullets con las ideas más valiosas del video"],
  "record": {"The Sauce Picks": {"win": 0, "loss": 0, "push": 0, "units": 0.0}}
}
```
- video_id (obligatorio): id del video de YouTube del que sale el pick, igual al video_id de su entrada en sources. El sitio lo usa para enlazar el timestamp al video correcto cuando hay varios videos en la semana.
- market: moneyline | spread | total | player_prop | team_prop | parlay | futures.
- category (misma taxonomía que mis apuestas): ml, ml_1h, spread, total, td_scorer, pass_yds, pass_comp, rush_yds, rec_yds, receptions, other.
- confidence: alta | media | baja, inferido del tono ("lock", "best bet", "love this" = alta). Márcalo como inferido.
- odds y line: solo si se dicen en el video. Si no, null. No inventes momios.
- verified: false siempre que el dato venga solo del audio. Corrige nombres mal transcritos contra el roster si puedes y déjalo anotado en reasoning.
- result: win | loss | push | void | null. Lo llena grade_picks.py (moneyline, spread, total). Props: null salvo result_manual.
- confidence_note, also_in (ids de otros videos donde se repite el mismo pick, para no duplicarlo) y notes son opcionales.
- status: "ok" o "pendiente_transcripcion" (con status_note) cuando la semana existe pero aún no se transcribió.

### 5.2 Mis apuestas (data/my_bets.json)
Una fila por boleto con sus legs. El _schema completo está en el archivo. Campos clave además de los obvios:
- followed_channel: "The Sauce Picks" si el boleto sigue un pick del canal, "mixto" si combina, null si es idea propia. channel_pick_ids: ids de data/picks que se siguieron. Así se mide "mis picks junto con Sauce" vs propios.
- legs[].source: propio | sauce | otro. legs[].team: abreviatura del equipo.
- free_bet true: el stake no cuenta como invertido. boost true: se registra el momio antes del boost en odds_before_boost_american.
- validated false hasta que yo confirme la extracción viendo la tabla resumen.
- Deduplica por ticket_id. Boletos colapsados en la captura (solo encabezado con "PERDIDO" o "CERRAR APUESTA"): legs: [] y legs_visible: false. No inventes legs. Si un dato no se lee: null + notes.

### 5.3 Momios (data/odds/{season}-W{nn}.json)
entries: [{"pick_id": "4o0fpns6Gm0-01", "book": "playdoit" | "draftea", "odds_american": -115 | "odds_decimal": 1.87, "captured_at": "2026-09-26T09:00", "source": "captura IMG_9201.png" | "manual"}].
compare_odds.py llena comparison (mejor casa, diferencia %, probabilidad implícita). Solo se registran momios vistos en la casa (captura o manual). Nada inventado.

### 5.4 Bankroll (data/bankroll_2026.json)
Mismo modelo que NFL BETS.xlsx: una fila por semana NFL con deposito y retiro; neto = retiro - deposito. Se actualiza al cierre de cada semana (lunes) con `python scripts/bankroll.py set --week N --deposito X --retiro Y`. bankroll.py calcula acumulado, restante antes de parar, nivel (verde hasta -5,000, amarillo hasta -8,000, rojo hasta -10,000, detenido) y estado ACTIVO / DETENIDO. El neto por boletos (my_bets.json) se muestra solo como contraste; la fuente de verdad del stop loss es el ledger.
retiro: null significa retiro pendiente de capturar (el neto semanal queda null). retiros_sin_asignar (nivel ledger) guarda retiros reportados en total sin desglose por semana: sí cuentan en el neto total y se suman al acumulado en la última semana con depósito. Cuando se conozca la semana, mover el monto a retiro de esa semana y restarlo de retiros_sin_asignar (edición manual del JSON). `set --retiro null` marca un retiro como pendiente.
Presupuesto semanal de referencia (Excel, hoja Distribución): 1,000 MXN = 500 dos mejores jugadas + 150 crear apuesta 1 + 150 crear apuesta 2 + 150 parlay soñador + 50 parlay lotería.

## 6. Análisis

### 6.1 Mis tendencias (analyze_my_bets.py -> data/my_bets_analysis.json)
Todas las métricas con n visible y advertencia si n < 10: global (boletos, invertido, cobrado, profit, ROI, hit rate), por tipo (single/parlay/sgp), por número de legs (hit rate real vs probabilidad implícita), por categoría de leg (la más importante), "leg que me mata" (parlays perdidos por una sola leg y su categoría), por equipo, por casa, boosts y apuestas gratis, por horario (madrugada vs normal), por origen (siguiendo canal vs propio), calibración por probabilidad implícita, y la sección "Qué sí / Qué no" con reglas que citan su n. Con muestras chicas se dice explícitamente.

### 6.2 Historial 2024 vs 2025 (analyze_history.py -> data/history/analysis.json)
Neto, ROI, semanas ganadoras, rachas perdedoras, drawdown, por fase (pre/reg/post), por tramo (W1-4, W5-12, W13-18), mensual y acumulado. Genera "reglas_con_datos" para el sitio.

## 7. Sitio (docs/)
HTML + CSS + JS vanilla, sin build, mobile first, modo oscuro por defecto. Chart.js desde cdnjs.
Pestañas: Bankroll 2026 | Mis tendencias | Historial 24/25 | Semana 3 | Semana 4 | ... (deep link #bankroll, #tendencias, #historial, #w03).
- Semana: encabezado con videos fuente, consenso entre canales arriba, tarjetas de picks con momio, confianza, LOCK, No verificado, timestamp con link al segundo del video, resultado, etiqueta ✓ tu fuerte / ⚠ tu débil (solo si n >= 5 en esa category), comparación Playdoit vs Draftea con la mejor resaltada, insights del video y récord del canal (W-L-P y unidades).
- Bankroll 2026: neto acumulado, límite, restante, semáforo, gráfica del acumulado con línea en -10,000, ledger semanal, distribución del presupuesto, lecciones aprendidas.
- Mis tendencias: KPIs, gráficas, Qué sí / Qué no, lista de boletos.
- Historial: 2024 vs 2025.
- Botón "Ocultar montos". Si config.site.show_amounts es false, build_site.py ya publica los montos como "oculto".
- Footer: "Solo para análisis personal. No es asesoría de apuestas."

## 8. Proceso semanal (weekly_prompt.md)
1. git pull.
2. python scripts/fetch_videos.py
3. python scripts/fetch_transcripts.py
4. Leer cada data/transcripts/{video_id}.txt y extraer picks + insights al JSON de su semana (5.1). Si un video no tiene picks NFL, registrarlo en videos_processed.json con n_picks 0 y saltarlo. Registrar cada video procesado: {video_id: {season, week, processed_at, n_picks}}.
5. python scripts/grade_picks.py (si ESPN falla, result null y avisar en el log).
6. python scripts/build_site.py y validar que docs/data cargue.
7. Commit "picks: {season}-W{nn} ({n} picks, {m} videos)" y push a main.
8. Resumen corto en logs/{fecha}.md (videos, picks, errores).

## 9. Capturas en Google Drive
Carpetas (ya creadas, dueño mazothecoach@gmail.com):
- MazoPicks: https://drive.google.com/drive/folders/1GOR9QrpLpDB3vb78JRK0sS2SPkL_GJ0L
- MazoPicks/capturas_boletos (id 1GQqt5mmUYAUpNsoF4nJCurn4_L-uUnlr): capturas de boletos de Playdoit y Draftea.
- MazoPicks/capturas_momios (id 1b668Kyl-iCDSTewqbgz9EFVtnoOM7jJH): capturas de los momios de un mismo pick en cada casa.
Formatos que Claude puede leer desde Drive: PNG y JPEG. HEIC no (exportar a JPEG antes).
Proceso en una sesión de Claude Code web: listar archivos nuevos de la carpeta (comparar contra data/screenshots_processed.json), leer cada imagen, extraer boletos a my_bets.json (validated false), mostrar tabla resumen para que yo valide, marcar en screenshots_processed.json, correr analyze_my_bets.py y build_site.py, commit y push.

## 10. Automatización en Windows
run_weekly.ps1 corre Claude Code en modo headless con weekly_prompt.md y guarda la salida en logs/. Confirma los flags con `claude --help` antes de dejarlos fijos. Programador de tareas: sábado 08:00 y domingo 09:00 (CDMX), "ejecutar tan pronto como sea posible si se omitió", "activar el equipo para ejecutar esta tarea". Muéstrame el comando antes de registrarlo.

## 11. Pendientes de la primera corrida
1. En Windows: crear venv, instalar requirements.txt, probar fetch_transcripts.py con los 4 videos de Semana 3 (4o0fpns6Gm0, gM-02rLbR9w, 3zqeqSP3rao, NRYYHPXEjbc) y extraer picks a data/picks/2026-W03.json (cambiar status a "ok").
2. Subir las 17 capturas de boletos a Drive/capturas_boletos en PNG o JPEG y extraerlas a my_bets.json (ya hay 2 registradas desde el plan inicial, validated false).
3. Depósitos y retiros de Week 1 a 3 ya capturados en data/bankroll_2026.json (depósitos 1,150, 3,700 y 2,300 MXN; retiros 4,800 MXN en total en retiros_sin_asignar). Falta el desglose de retiros por semana: al conocerlo, mover cada monto a retiro de su semana y restarlo de retiros_sin_asignar.
4. Crear la rama main desde claude/fervent-turing-nwmlb0 (en GitHub: Branches > New branch > main, source claude/fervent-turing-nwmlb0), ponerla como rama predeterminada (Settings > General > Default branch) y activar GitHub Pages (Settings > Pages > Deploy from a branch > main, /docs). Los workflows solo corren en main. Decidir show_amounts (el repo es público).
5. Registrar las tareas programadas del sábado y domingo.

## 12. Agregar canales después
Solo edito channels.json. El pipeline no debe requerir cambios de código para un canal nuevo.
