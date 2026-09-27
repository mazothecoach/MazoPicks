# MazoPicks: corrida semanal (claude -p)

## Reglas de trabajo (del usuario, obligatorias)

> Never do the work yourself. Always dispatch a sub-agent. Don't always use Fable. Use Opus 5.5 for easier tasks. Model routing: Fable 5.1 for architecture, hard bugs, review; Opus 5.5 for edits, tests, docs, refactors; Haiku 4.5 for lookups and summaries; pass model on every Agent call. Delegation: one sub-agent per task, plan first; run independent sub-agents in parallel; read the report, never the files.

Tú (agente principal) solo planeas, despachas sub-agentes, lees sus reportes y decides. Cada sub-agente recibe en su prompt las reglas de este archivo que le aplican (sobre todo "No inventar" y "Formato").

## Contexto

- Corres sin supervisión en la compu Windows de Mazo, lanzado por `run_weekly.ps1` desde el Programador de tareas: sábado 08:00 y domingo 09:00 hora CDMX (America/Mexico_City, UTC-6 todo el año). Nadie va a contestar preguntas: decide con estas reglas y anota cualquier duda en el log.
- Directorio de trabajo: raíz del repo MazoPicks (público: mazothecoach/MazoPicks; el sitio se publica desde `/docs` en `main`). El entorno `.venv` ya está activo: usa `python`, no `python3`. La herramienta Bash es Git Bash.
- Desde esta compu YouTube y ESPN sí son accesibles (desde la nube de Claude no).
- The Sauce Picks (@KyleKirms) publica varios videos por semana NFL: jueves (TNF), sábado noche o domingo temprano (picks del domingo) y shows en vivo. Todos cuentan para la misma semana. La semana NFL va de martes a lunes; si el título dice "Week N", ese número manda (`python scripts/nfl_week.py FECHA "TÍTULO"`).
- La corrida es idempotente: `data/videos_processed.json` dice qué videos ya se procesaron. Correr sábado y domingo no debe duplicar nada.
- Si `CLAUDE.md` y este archivo difieren en un esquema, manda `CLAUDE.md`.

## No inventar (reglas duras)

1. Nunca inventes momios. `odds_american` y `odds_decimal` solo se llenan si el momio se dice en el video; si no, `null`. No busques momios en internet para llenar huecos.
2. Tampoco inventes líneas, jugadores, partidos ni resultados. Si un número no se entiende en la transcripción, `line: null` y explícalo en `reasoning`.
3. Todo lo que sale solo del audio es "No verificado": `verified: false` siempre en esta corrida. En el log, cada pick nuevo se lista con la etiqueta "No verificado". La confianza es inferida del tono: agrega `"confidence_note": "Inferido del audio"`.
4. `result` siempre `null` al extraer. Solo `grade_picks.py` lo llena. Nunca lo pongas a mano.
5. Si ESPN falla (grade_picks.py imprime "ESPN falló"), los picks se quedan con `result: null` y lo anotas en el log. No reintentes con otras fuentes.
6. WebFetch solo para consultas de apoyo (por ejemplo confirmar local y visitante o la fecha de un partido en el scoreboard de ESPN), nunca para momios ni resultados.

## Formato

- Todo texto en español (reasoning, insights, notas, log).
- Prohibido el carácter guion largo (em dash, U+2014) en cualquier archivo, JSON, log o mensaje de commit. Usa punto, coma, dos puntos o paréntesis.
- Edita los JSON con un script corto de Python (`json.load` y `json.dump(..., ensure_ascii=False, indent=2)`, UTF-8), no a mano.

## No tocar

`scripts/`, `channels.json`, `data/config.json`, `data/my_bets.json`, `data/bankroll_2026.json`, `data/history/`, `CLAUDE.md`, `README.md`, `weekly_prompt.md`, `run_weekly.ps1`, `.github/`. `docs/` y los archivos generados de `data/` solo cambian a través de los scripts. Nada de `git push --force` ni reescribir historial.

## Plan de delegación

| Paso | Sub-agente | Modelo |
|---|---|---|
| 1 a 3: git pull, fetch_videos, fetch_transcripts | uno | Haiku 4.5 |
| 4a: extraer picks e insights de un video | uno por video, en paralelo | Opus 5.5 |
| 4b: escribir el JSON de la semana y videos_processed.json | uno | Opus 5.5 |
| 5 y 6: grade_picks, build_site y validación | uno | Haiku 4.5 |
| 7 y 8: commit, push y log | uno | Haiku 4.5 |
| Solo si algo falla raro (traceback, JSON corrupto, conflicto de git) | diagnóstico | Fable 5.1 |

Pasa `model` en cada llamada a Agent. Pide a cada sub-agente un reporte corto con lo que hizo, conteos y errores.

## Pasos

### 1. Actualizar el repo
`git pull --rebase --autostash`. Si falla, anótalo y sigue con lo que hay local.

### 2. Buscar videos nuevos
`python scripts/fetch_videos.py`. Escribe `data/videos_new.json` con `video_id`, `title`, `channel`, `url`, `published`, `season`, `week`. Si hay 0 videos nuevos, salta al paso 5. Si yt-dlp reporta bloqueo de YouTube, anótalo en el log (Mazo puede definir `YTDLP_EXTRA_ARGS="--cookies-from-browser chrome"`).

### 3. Transcribir
`python -u scripts/fetch_transcripts.py`. Genera `data/transcripts/{video_id}.txt` (encabezado con `# transcript_method:` y líneas `[mm:ss] texto`). Un video que marque `[FALLÓ]` NO se marca como procesado: se reintenta en la siguiente corrida y va al log con su error.
Usa siempre `python -u` (sin eso, si el proceso muere se pierde la salida). Si un video no tiene subtítulos automáticos y `GEMINI_API_KEY` está definida, el método gemini consume cuota (free tier: 20 requests/día, cada reintento cuenta): anota en el log cuántas llamadas se hicieron (el script imprime `[gemini] {video_id}: N llamada(s)` por video y `Presupuesto Gemini: ...` al final) y cualquier línea `Verificación: ... AVISO` (timestamps posiblemente corridos).

### 4. Extraer picks e insights

**4a. Por video (un sub-agente Opus 5.5 por transcripción, en paralelo).** Cada uno lee `data/transcripts/{video_id}.txt` y devuelve en su reporte un bloque JSON con `picks` e `insights` de ese video. No escribe archivos.

Qué cuenta como pick:
- Solo NFL. Ignora college, NBA, MLB y demás.
- Una recomendación explícita del host del canal ("I'm taking", "give me", "my pick", "I like X -3", "lock", "best bet"). Un "lean" también cuenta, con `confidence: "baja"`.
- Si el host recomienda un parlay: un pick con `market: "parlay"`, `category: "other"` y las legs en `selection`. Futuros (MVP, Super Bowl, total de victorias): `market: "futures"`.
- Picks de invitados o co-hosts no son picks del canal: van como insight mencionando quién lo dijo. Si no está claro quién habla, regístralo como pick y agrega `"notes": "Posible pick de invitado"`.
- Un mismo pick repetido dentro del video se registra una vez.

Esquema de cada pick (igual a CLAUDE.md 5.1):

```json
{
  "id": "4o0fpns6Gm0-01",
  "channel": "The Sauce Picks",
  "video_id": "4o0fpns6Gm0",
  "game": "ATL @ GB",
  "kickoff": "2026-09-24",
  "market": "spread",
  "category": "spread",
  "selection": "GB Packers -3.5",
  "line": -3.5,
  "odds_american": null,
  "odds_decimal": null,
  "confidence": "media",
  "confidence_note": "Inferido del audio",
  "is_lock": false,
  "units": null,
  "reasoning": "Una o dos frases en español con el porqué que da el host.",
  "timestamp": "12:34",
  "verified": false,
  "result": null,
  "result_manual": null
}
```

Reglas por campo:
- `id`: `"{video_id}-{nn}"`, `nn` de dos dígitos desde 01, en orden de aparición dentro del video.
- `channel`: nombre exacto de `channels.json`.
- `video_id` (obligatorio): id del video de YouTube de donde sale el pick, el mismo que su entrada en `sources`. El sitio lo usa para que el link del `timestamp` abra el video correcto cuando hay varios videos en la semana. Nunca lo omitas ni lo dejes `null`.
- `game`: `"VISITANTE @ LOCAL"` con abreviaturas de ESPN (ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WSH). Si dudas quién es local, confírmalo en `https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=2026&seasontype=2&week=N`. `kickoff`: fecha del partido (YYYY-MM-DD) o `null` si no se pudo confirmar.
- `market`: moneyline | spread | total | player_prop | team_prop | parlay | futures.
- `category`: ml | ml_1h | spread | total | td_scorer | pass_yds | pass_comp | rush_yds | rec_yds | receptions | other.
- `selection`: texto que el calificador pueda leer. Moneyline y spread: abreviatura y nombre del equipo, más la línea ("KC Chiefs ML", "GB Packers -3.5"). Totales: empieza con "Over" o "Under" más la línea ("Over 47.5"). Props: jugador, dirección, línea y estadística ("Jordan Love over 20.5 completions").
- `line`: número (spread del equipo elegido, total o línea del prop) o `null`.
- `odds_american` / `odds_decimal`: solo si se dicen en el video. Si dice uno, puedes convertir al otro (americano positivo: 1 + a/100; negativo: 1 + 100/|a|; decimal con 2 decimales). Si no dice momio, ambos `null`.
- `confidence`: alta | media | baja, inferida del tono ("lock", "best bet", "love this", "hammer" = alta; lean, "sprinkle", "small play" = baja; lo demás media).
- `is_lock`: `true` solo si lo llama explícitamente lock, best bet o pick of the week.
- `units`: número solo si lo dice ("two units"); si no, `null`.
- `reasoning`: 1 a 2 frases en español, parafraseadas. Si corregiste un nombre mal transcrito contra el roster, anótalo aquí ("Transcripción decía 'Jordan Loves'").
- `timestamp`: `mm:ss` de la línea de la transcripción donde da el pick (puede pasar de 59 minutos, por ejemplo `75:12`).
- `verified`: `false`. `result`: `null`. `result_manual`: `null`.

Insights: 3 a 6 strings por video, en español, cada uno autocontenido (lesiones, clima, tendencias, movimiento de línea, picks de invitados). Son strings, no objetos.

Si el video no tiene picks NFL, el reporte lo dice explícitamente con `n_picks: 0`.

**4b. Escritura (un sub-agente Opus 5.5).** Con los reportes de 4a:
- Archivo: `data/picks/{season}-W{nn}.json` usando `season` y `week` de `data/videos_new.json`. Si no existe, créalo con `season`, `week`, `generated_at`, `status`, `sources: []`, `picks: []`, `insights: []`.
- `sources`: agrega o actualiza la entrada de cada video (`channel`, `video_id`, `title`, `url`, `published`, `transcript_method` tomado del encabezado del .txt).
- `picks`: agrega los nuevos. Si ya existen picks con ese `video_id` (corrida repetida), reemplázalos en vez de duplicar. Si el mismo canal ya tiene en esa semana el mismo pick (mismo `game`, `market`, `selection` y `line`) de otro video, no lo dupliques: agrega el `video_id` nuevo a un campo `also_in` del pick existente. Si cambió de lado o de línea, es un pick nuevo y lo anotas en `reasoning`.
- `insights`: agrega los nuevos sin repetir textos.
- `status`: `"ok"` si ya se procesó al menos un video de la semana; si alguno de `sources` sigue sin transcripción, dilo en `status_note`. Si ya no falta ninguno, quita `status_note`. `generated_at`: ahora, ISO con `-06:00`.
- `data/videos_processed.json`: por cada video procesado (incluidos los de 0 picks) `{"video_id": {"season": 2026, "week": 3, "processed_at": "2026-09-27T09:05:00-06:00", "n_picks": 5}}`. Los que fallaron en el paso 3 no se marcan.
- Valida: todos los `id` únicos, JSON válido y sin guion largo:

```bash
python -c "import json,pathlib,sys
bad=[]
for p in list(pathlib.Path('data').rglob('*.json'))+list(pathlib.Path('logs').glob('*.md')):
    t=p.read_text(encoding='utf-8')
    if p.suffix=='.json': json.loads(t)
    if chr(0x2014) in t: bad.append(str(p))
print('archivos con guion largo:', bad); sys.exit(1 if bad else 0)"
```

### 5. Calificar
`python scripts/grade_picks.py`. Los partidos que aún no se juegan se quedan en `null` (normal). Si la salida dice "ESPN falló", deja todo en `result: null` y anótalo en el log.

### 6. Construir el sitio
`python scripts/build_site.py`. Debe terminar con "docs/data listo". Valida que carguen todos los JSON: `python -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('docs/data').rglob('*.json')]; print('ok')"`. Si falla, no hagas commit de `docs/` roto: diagnóstico con Fable 5.1 y anótalo.

### 7. Commit y push
- `git add -A data docs` (nunca `scripts/` ni archivos fuera de esas carpetas; `data/videos_new.json` ya está en .gitignore).
- Mensaje con videos nuevos: `picks: {season}-W{nn} ({n} picks, {m} videos)`, donde `n` son los picks nuevos de esta corrida y `m` los videos procesados (incluidos los de 0 picks). Si hubo varias semanas: `picks: 2026-W03 (5 picks, 2 videos), 2026-W04 (1 picks, 1 videos)`.
- Sin videos nuevos: si grade_picks calificó algo, `grade: picks calificados (local)`; si solo cambió el sitio, `site: rebuild docs/data (local)`. Si `git status --porcelain` está vacío, no hay commit.
- `git pull --rebase --autostash` y luego `git push origin HEAD:main`. Si el push es rechazado, repite pull y push una vez; si vuelve a fallar, anótalo en el log (run_weekly.ps1 reintenta el push al final).

### 8. Log
Escribe `logs/{fecha}.md` (fecha local CDMX, `YYYY-MM-DD`). Si ya existe (segunda corrida del día), agrega una sección nueva al final. Después `git add logs/{fecha}.md`, commit `log: {fecha}` y push igual que en el paso 7.

```markdown
## Corrida {fecha} {HH:MM} CDMX

- Semana: 2026-W03
- Videos nuevos: 2 (4o0fpns6Gm0 "Week 3 NFL Picks...", gM-02rLbR9w "Falcons vs Packers...")
- Transcripción: 4o0fpns6Gm0 youtube-transcript-api; gM-02rLbR9w gemini (4 llamadas a Gemini, verificación OK)
- Picks nuevos: 6 (todos No verificado)
  - 4o0fpns6Gm0-01 ATL @ GB, GB Packers -3.5, confianza media (No verificado)
- Videos sin picks NFL (n_picks 0): ninguno
- Fallas: ninguna | "ESPN falló: ..." | "gM-02rLbR9w sin transcripción, se reintenta"
- Calificación: 3 de 8 pendientes calificados
- Commits: abc1234 picks: 2026-W03 (6 picks, 2 videos)
```

## Mensaje final

Termina con un resumen de 5 a 10 líneas (va a `logs/run_{fecha}.log`): semana, videos procesados, picks nuevos, fallas, commits y si el push salió bien.
