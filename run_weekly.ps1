<#
.SYNOPSIS
  MazoPicks: corrida semanal automatica (sabado 08:00 y domingo 09:00, hora CDMX).

.DESCRIPTION
  1. Se ubica en la carpeta del repo y activa .venv.
  2. git pull.
  3. Lee weekly_prompt.md y corre Claude Code en modo headless (claude -p).
  4. Si quedaron commits locales sin subir, hace git push.
  Toda la salida va a la consola y a logs\run_{fecha}.log (ignorado por git).
  El resumen de la corrida lo escribe Claude en logs\{fecha}.md.

  ADVERTENCIA: confirma los flags con `claude --help` antes de dejar esto programado.
  Los flags y los nombres de herramientas cambian entre versiones de Claude Code
  (por ejemplo, la herramienta de sub-agentes antes se llamaba "Task" y ahora "Agent").
  Si en modo headless se atora esperando permisos, revisa --permission-mode en `claude --help`.
  Pruebalo a mano una vez antes de programarlo:  .\run_weekly.ps1

  Requisitos: Python 3.11+ con .venv creado, Git for Windows, Claude Code (`claude`)
  con sesion iniciada (corre `claude` una vez a mano) y git con permiso de push a
  mazothecoach/MazoPicks.
#>

<# ===== Registrar las tareas programadas (copiar y pegar en PowerShell; aqui NO se ejecuta) =====
# Ajusta $repo a la ruta real del repo. Las horas son la hora local de la compu (CDMX).
$repo = "C:\Users\TU_USUARIO\MazoPicks"
$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$repo\run_weekly.ps1`"" `
    -WorkingDirectory $repo
# -StartWhenAvailable = "Ejecutar la tarea tan pronto como sea posible si se omitio un inicio programado"
# -WakeToRun          = "Activar el equipo para ejecutar esta tarea"
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
# Interactive: corre con tu sesion iniciada (puede estar bloqueada) y usa tus credenciales de git y claude.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "MazoPicks sabado 0800" -Action $accion -Settings $config -Principal $principal `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "08:00")
Register-ScheduledTask -TaskName "MazoPicks domingo 0900" -Action $accion -Settings $config -Principal $principal `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "09:00")

# Probar ya, ver resultado (LastTaskResult 0 = ok) y borrar si hace falta:
Start-ScheduledTask -TaskName "MazoPicks sabado 0800"
Get-ScheduledTaskInfo -TaskName "MazoPicks sabado 0800"
schtasks /Query /TN "MazoPicks domingo 0900" /V /FO LIST
Unregister-ScheduledTask -TaskName "MazoPicks sabado 0800" -Confirm:$false

# Para que "activar el equipo" funcione: Panel de control > Opciones de energia > Configuracion avanzada >
# Suspender > Permitir temporizadores de reactivacion = Habilitar.
#>

Set-Location $PSScriptRoot
$ErrorActionPreference = "Continue"

$fecha  = Get-Date -Format "yyyy-MM-dd"
$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runLog = Join-Path $logDir "run_$fecha.log"

# UTF-8 para acentos en consola, en la salida de Python y en el stdin de claude.
$utf8 = New-Object System.Text.UTF8Encoding $false
try { [Console]::OutputEncoding = $utf8 } catch { }
$OutputEncoding = $utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Write-Log([string]$msg) {
    "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg | Tee-Object -FilePath $runLog -Append
}

# Corre un bloque, junta todas sus salidas (*>&1) como texto y las manda a consola y al log.
function Invoke-Logged([scriptblock]$cmd) {
    & $cmd *>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $runLog -Append
}

Write-Log "=== MazoPicks corrida semanal $fecha ==="

# 1. Entorno virtual
$activate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Log "ERROR: no existe .venv. Crealo con: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt"
    exit 1
}
. $activate

$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Log "ERROR: no se encontro 'claude' en el PATH."
    exit 1
}

$rama = (git rev-parse --abbrev-ref HEAD 2>$null)
if ($rama -ne "main") { Write-Log "AVISO: la rama actual es '$rama', no main." }

# 2. git pull
Write-Log "git pull"
Invoke-Logged { git pull --rebase --autostash }
if ($LASTEXITCODE -ne 0) { Write-Log "AVISO: git pull fallo (codigo $LASTEXITCODE). Sigo con la copia local." }

# 3. Claude Code headless con weekly_prompt.md
$prompt = Get-Content -Path (Join-Path $PSScriptRoot "weekly_prompt.md") -Raw -Encoding UTF8
$tools  = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,Agent"
Write-Log "claude -p con weekly_prompt.md ($($prompt.Length) caracteres)"

# El prompt trae comillas dobles y saltos de linea. Windows PowerShell 5.1 (y pwsh < 7.3) no escapa
# las comillas internas al pasar argumentos, y claude.cmd (instalacion con npm) pasa por cmd.exe, que
# corta en el primer salto de linea. En esos casos el mismo prompt se manda por stdin, que claude -p acepta.
$usaStdin = ($claude.Source -notlike "*.exe") -or ($PSVersionTable.PSVersion -lt [version]"7.3")
if ($usaStdin) {
    Write-Log "Prompt por stdin (PowerShell $($PSVersionTable.PSVersion), $($claude.Source))"
    Invoke-Logged { $prompt | claude -p --allowedTools $tools }
} else {
    Invoke-Logged { claude -p $prompt --allowedTools $tools }
}
$codigoClaude = $LASTEXITCODE
Write-Log "claude termino con codigo $codigoClaude"

# 4. Push si quedaron commits sin subir (Claude ya hace push en el paso 7; esto es la red de seguridad)
Invoke-Logged { git fetch origin }
$pendientes = git rev-list --count '@{u}..HEAD' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Log "AVISO: la rama no tiene upstream; no pude revisar si hay commits sin subir."
} elseif ([int]$pendientes -gt 0) {
    Write-Log "Hay $pendientes commit(s) sin subir. git push."
    Invoke-Logged { git pull --rebase --autostash }
    Invoke-Logged { git push }
    if ($LASTEXITCODE -ne 0) { Write-Log "ERROR: git push fallo (codigo $LASTEXITCODE)." }
} else {
    Write-Log "Sin commits pendientes de subir."
}

Write-Log "=== Fin ==="
if ($null -eq $codigoClaude) { exit 1 }
exit $codigoClaude
