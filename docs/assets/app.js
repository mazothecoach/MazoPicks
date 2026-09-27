/* MazoPicks: front-end estático (JS vanilla, sin build ni frameworks).
 * Lee docs/data/*.json con rutas relativas y dibuja las pestañas.
 * Chart.js es opcional: si no carga, cada gráfica se oculta y quedan las tablas. */
(function () {
  'use strict';

  // =====================================================================
  // Constantes
  // =====================================================================

  const HIDE_KEY = 'mazopicks.ocultarMontos';
  const MASK = '•••';
  const NA = 's/d';
  const CHART_TIMEOUT_MS = 10000;
  const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

  const COLORS = {
    series: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181'],
    critical: '#d03b3b',
    text: '#f5f4f0',
    text2: '#c3c2b7',
    muted: '#8f8d86',
    grid: '#2c2c2a',
    axis: '#55544f',
    surface: '#1a1a19',
  };

  const CATEGORY_LABELS = {
    ml: 'Moneyline', ml_1h: 'Moneyline 1a mitad', spread: 'Spread', total: 'Total (O/U)',
    td_scorer: 'Anotador de TD', pass_yds: 'Yardas por pase', pass_comp: 'Pases completados',
    rush_yds: 'Yardas por tierra', rec_yds: 'Yardas por recepción', receptions: 'Recepciones', other: 'Otro',
  };
  const MARKET_LABELS = {
    moneyline: 'Moneyline', spread: 'Spread', total: 'Total', player_prop: 'Prop de jugador',
    team_prop: 'Prop de equipo', parlay: 'Parlay', futures: 'Futuros',
  };
  const TYPE_LABELS = { single: 'Sencilla', sencilla: 'Sencilla', sgp: 'SGP (mismo partido)', parlay: 'Parlay', teaser: 'Teaser', futures: 'Futuros' };
  const TICKET_STATUS = {
    won: ['Ganado', 'good'], lost: ['Perdido', 'bad'], open: ['Abierto', 'info'],
    cashed_out: ['Cash out', 'warn'], void: ['Anulado', 'neutral'],
  };
  const RESULTS = { win: ['Ganó', 'good'], loss: ['Perdió', 'bad'], push: ['Push', 'neutral'], void: ['Anulado', 'neutral'] };
  const CONFIDENCE_TONES = { alta: 'good', media: 'warn', baja: 'neutral' };
  const LEVELS = { verde: 'Verde', amarillo: 'Amarillo', rojo: 'Rojo', detenido: 'Detenido' };
  const LEVEL_COLORS = { verde: 'var(--good)', amarillo: 'var(--warn)', rojo: 'var(--bad)' };
  const PHASES = [['pre', 'Pretemporada'], ['reg', 'Temporada regular'], ['post', 'Postemporada']];
  const TRAMOS = [['temprano_w1_w4', 'Temprano (W1 a W4)'], ['medio_w5_w12', 'Medio (W5 a W12)'], ['tarde_w13_w18', 'Tarde (W13 a W18)']];
  const HORARIO_ORDER = ['madrugada (00-06)', 'mañana (06-12)', 'tarde (12-18)', 'noche (18-24)', 'desconocido'];
  const LEGS_ORDER = ['1', '2', '3', '4+'];
  const TRANSCRIPT_METHODS = {
    'youtube-transcript-api': 'subtítulos de YouTube (API)',
    'yt-dlp-auto-subs': 'subtítulos automáticos (yt-dlp)',
    'whisper-local': 'Whisper local (audio)',
  };
  const SHORT_WEEKS = { 'Super Wild Card': 'WC', Divisional: 'Div', Conference: 'Conf', 'Super Bowl': 'SB' };

  const DATA_FILES = {
    index: 'data/index.json',
    config: 'data/config.json',
    status: 'data/bankroll_2026_status.json',
    bets: 'data/my_bets.json',
    analysis: 'data/my_bets_analysis.json',
    history: 'data/history/analysis.json',
    b2024: 'data/history/bankroll_2024.json',
    b2025: 'data/history/bankroll_2025.json',
    dist: 'data/history/distribucion_semanal.json',
    channels: 'data/channels.json',
  };

  // =====================================================================
  // Estado
  // =====================================================================

  const state = {
    hide: readHide(),
    data: {},
    failed: [],
    tabs: [],
    current: null,
    rendered: new Set(),
    charts: {},
    weekData: {},
    filters: {},
  };
  const chartLib = { status: 'loading', pending: [] };

  function readHide() {
    try {
      return window.localStorage.getItem(HIDE_KEY) === '1';
    } catch (err) {
      return false;
    }
  }

  function writeHide(value) {
    try {
      window.localStorage.setItem(HIDE_KEY, value ? '1' : '0');
    } catch (err) {
      /* Sin localStorage (modo privado o bloqueado): solo dura esta visita. */
    }
  }

  // =====================================================================
  // Utilidades
  // =====================================================================

  function esc(value) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => map[c]);
  }

  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const obj = (v) => (isObj(v) ? v : {});
  const pad2 = (n) => String(n).padStart(2, '0');
  const fixZero = (n) => (Object.is(n, -0) ? 0 : n);
  const uniq = (list) => Array.from(new Set(list));
  const $ = (sel, root) => (root || document).querySelector(sel);

  function toNum(v) {
    if (isNum(v)) return v;
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
    return null;
  }

  function capitalize(s) {
    const text = String(s == null ? '' : s);
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function lastIndex(list, fn) {
    for (let i = list.length - 1; i >= 0; i -= 1) if (fn(list[i])) return i;
    return -1;
  }

  function rankIn(order, key) {
    const i = order.indexOf(key);
    return i === -1 ? order.length : i;
  }

  function normText(s) {
    return String(s == null ? '' : s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  function safeUrl(url) {
    return typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null;
  }

  // =====================================================================
  // Formatos
  // =====================================================================

  function isHiddenAmount(v) {
    return state.hide || v === 'oculto';
  }

  function fmtNum(v, digits) {
    const n = toNum(v);
    if (n === null) return NA;
    const d = digits || 0;
    const r = fixZero(Number(n.toFixed(d)));
    const sign = r < 0 ? '-' : '';
    return sign + Math.abs(r).toLocaleString('es-MX', { maximumFractionDigits: d });
  }

  /** Monto MXN. opts.signed agrega +, opts.unit=false quita "MXN". */
  function fmtMoney(v, opts) {
    const o = opts || {};
    if (isHiddenAmount(v)) return MASK;
    if (!isNum(v)) return NA;
    const n = fixZero(Math.round(v));
    const sign = n < 0 ? '-' : (o.signed && n > 0 ? '+' : '');
    return sign + Math.abs(n).toLocaleString('es-MX') + (o.unit === false ? '' : ' MXN');
  }

  function toneClass(v) {
    if (!isNum(v)) return '';
    if (v > 0) return 'pos';
    return v < 0 ? 'neg' : '';
  }

  /** Monto como HTML; con signo lleva color verde/rojo. */
  function money(v, opts) {
    const o = opts || {};
    const cls = o.signed && !isHiddenAmount(v) ? toneClass(v) : '';
    return `<span class="num ${cls}">${esc(fmtMoney(v, o))}</span>`;
  }

  /** Porcentaje desde fracción (0.16 -> 16%). */
  function fmtPct(v, opts) {
    const o = opts || {};
    const n0 = toNum(v);
    if (n0 === null) return NA;
    const d = o.digits || 0;
    const n = fixZero(Number((n0 * 100).toFixed(d)));
    const sign = n < 0 ? '-' : (o.signed && n > 0 ? '+' : '');
    return sign + Math.abs(n).toLocaleString('es-MX', { maximumFractionDigits: d }) + '%';
  }

  function pctSigned(v) {
    return `<span class="num ${toneClass(toNum(v))}">${esc(fmtPct(v, { signed: true }))}</span>`;
  }

  function fmtAmerican(v) {
    const n = toNum(v);
    if (n === null) return NA;
    const r = Math.round(n);
    return (r > 0 ? '+' : r < 0 ? '-' : '') + Math.abs(r);
  }

  function fmtDecimal(v) {
    const n = toNum(v);
    return n === null ? NA : n.toFixed(2);
  }

  function fmtUnits(v) {
    const n = toNum(v);
    if (n === null) return NA;
    const r = fixZero(Number(n.toFixed(2)));
    return (r > 0 ? '+' : r < 0 ? '-' : '') + Math.abs(r).toLocaleString('es-MX', { maximumFractionDigits: 2 }) + ' u';
  }

  /** Oculta montos dentro de textos libres ("neto -383 MXN"). */
  function maskText(s) {
    const text = String(s == null ? '' : s);
    return state.hide ? text.replace(/[+-]?\d[\d,.]*(?=\s*MXN)/g, MASK) : text;
  }

  /** "2026-09-27T19:15" -> "27 sep 2026, 19:15" sin conversiones de zona horaria. */
  function fmtDate(s, withTime) {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(String(s || ''));
    if (!m) return s ? String(s) : NA;
    const base = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] || m[2]} ${m[1]}`;
    return withTime !== false && m[4] ? `${base}, ${m[4]}:${m[5]}` : base;
  }

  /** "12:34" -> 754, "1:02:03" -> 3723. */
  function tsToSeconds(ts) {
    const t = String(ts == null ? '' : ts).trim();
    if (!/^\d{1,3}(:\d{1,2}){1,2}$/.test(t)) return null;
    return t.split(':').reduce((acc, part) => acc * 60 + Number(part), 0);
  }

  function withTime(url, secs) {
    try {
      const u = new URL(url);
      u.searchParams.set('t', `${secs}s`);
      return u.toString();
    } catch (err) {
      return null;
    }
  }

  function shortWeek(label) {
    const text = String(label || '');
    const m = /^Week (\d+)( Pre)?$/.exec(text);
    if (m) return (m[2] ? 'P' : 'W') + m[1];
    return SHORT_WEEKS[text] || text;
  }

  function catLabel(key) {
    const fromAnalysis = obj(obj(obj(state.data.analysis).por_categoria_leg)[key]).label;
    return fromAnalysis || CATEGORY_LABELS[key] || key || 'Sin categoría';
  }

  function bookName(key) {
    const book = arr(obj(state.data.config).books).find((b) => b && b.key === key);
    if (book && book.name) return book.name;
    return key && key !== '?' ? capitalize(key) : 'Casa desconocida';
  }

  function typeLabel(key) {
    return TYPE_LABELS[key] || capitalize(key || 'Otro');
  }

  // =====================================================================
  // Piezas de HTML
  // =====================================================================

  function badge(text, tone, title) {
    const t = title ? ` title="${esc(title)}"` : '';
    return `<span class="badge badge-${tone || 'neutral'}"${t}>${esc(text)}</span>`;
  }

  function sampleBadge(flag) {
    return flag ? badge('muestra chica', 'warn', 'Menos de 10 casos: tómalo como orientativo') : '';
  }

  function kpi(label, valueHtml, sub) {
    return `<div class="card kpi"><div class="kpi-label">${esc(label)}</div>` +
      `<div class="kpi-value">${valueHtml}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
  }

  function panelTitle(title, sub) {
    return `<div class="panel-title"><h1>${esc(title)}</h1>${sub ? `<span class="muted small">${esc(sub)}</span>` : ''}</div>`;
  }

  function block(title, body, opts) {
    const o = opts || {};
    return `<section class="block"><div class="block-head"><h2>${esc(title)}</h2>${o.extra || ''}</div>` +
      `${o.note ? `<p class="block-note">${esc(o.note)}</p>` : ''}${body}</section>`;
  }

  function banner(tone, title, text) {
    const role = tone === 'bad' ? 'alert' : 'status';
    return `<div class="banner banner-${tone}" role="${role}"><strong>${esc(title)}</strong>` +
      `${text ? `<p>${esc(text)}</p>` : ''}</div>`;
  }

  function empty(text) {
    return `<p class="empty">${esc(text)}</p>`;
  }

  function markList(items, kind) {
    return `<ul class="list-mark${kind ? ` list-${kind}` : ''}">${items.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>`;
  }

  const th = (label, cls) => ({ html: esc(label), cls });
  const numCell = (html, extraCls) => ({ html, cls: `r${extraCls ? ` ${extraCls}` : ''}` });

  function cellHtml(c, tag) {
    const x = isObj(c) ? c : { html: c };
    let attrs = x.cls ? ` class="${x.cls}"` : '';
    if (x.colspan) attrs += ` colspan="${x.colspan}"`;
    if (x.rowspan) attrs += ` rowspan="${x.rowspan}"`;
    return `<${tag}${attrs}>${x.html == null ? '' : x.html}</${tag}>`;
  }

  /** head: lista de celdas o lista de filas; rows: arrays de celdas o {cells, cls}. */
  function table(head, rows, label) {
    const headRows = Array.isArray(head[0]) ? head : [head];
    const thead = headRows.map((r) => `<tr>${r.map((c) => cellHtml(typeof c === 'string' ? th(c) : c, 'th')).join('')}</tr>`).join('');
    const tbody = rows.map((r) => {
      const row = Array.isArray(r) ? { cells: r } : r;
      return `<tr${row.cls ? ` class="${row.cls}"` : ''}>${row.cells.map((c) => cellHtml(c, 'td')).join('')}</tr>`;
    }).join('');
    const aria = label ? ` role="region" tabindex="0" aria-label="${esc(label)}"` : '';
    return `<div class="table-wrap"${aria}><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
  }

  // =====================================================================
  // Chart.js (opcional)
  // =====================================================================

  function initChartLib() {
    if (window.Chart) {
      chartReady();
      return;
    }
    if (window.chartjsFailed) {
      chartFailed();
      return;
    }
    const el = document.getElementById('chartjs');
    if (!el) {
      chartFailed();
      return;
    }
    el.addEventListener('load', () => (window.Chart ? chartReady() : chartFailed()));
    el.addEventListener('error', chartFailed);
    window.setTimeout(() => {
      if (chartLib.status === 'loading') chartFailed();
    }, CHART_TIMEOUT_MS);
  }

  function chartReady() {
    if (chartLib.status === 'ready') return;
    chartLib.status = 'ready';
    applyChartDefaults();
    chartLib.pending.splice(0).forEach(drawChart);
  }

  function chartFailed() {
    if (chartLib.status !== 'loading') return;
    chartLib.status = 'failed';
    chartLib.pending.forEach((item) => item.el.classList.add('chart-failed'));
  }

  function applyChartDefaults() {
    const d = window.Chart.defaults;
    d.color = COLORS.muted;
    d.borderColor = COLORS.grid;
    d.font.family = getComputedStyle(document.body).fontFamily;
    d.font.size = 12;
    d.maintainAspectRatio = false;
    d.plugins.legend.labels.color = COLORS.text2;
    d.plugins.legend.labels.boxWidth = 12;
    d.plugins.legend.labels.boxHeight = 12;
    Object.assign(d.plugins.tooltip, {
      backgroundColor: '#0d0d0d', borderColor: 'rgba(255,255,255,0.2)', borderWidth: 1,
      titleColor: COLORS.text, bodyColor: COLORS.text2, padding: 10, cornerRadius: 8, boxPadding: 4,
    });
  }

  function queueChart(item) {
    if (chartLib.status === 'ready') {
      drawChart(item);
      return;
    }
    chartLib.pending.push(item);
    if (chartLib.status === 'failed') item.el.classList.add('chart-failed');
  }

  function drawChart(item) {
    if (!item.el.isConnected) return;
    const canvas = item.el.querySelector('canvas');
    if (!canvas) return;
    try {
      const chart = new window.Chart(canvas, item.config());
      item.el.classList.remove('chart-failed');
      (state.charts[item.tabId] = state.charts[item.tabId] || []).push(chart);
    } catch (err) {
      console.error('No se pudo dibujar la gráfica', err);
      item.el.classList.add('chart-failed');
    }
  }

  function destroyCharts(tabId) {
    arr(state.charts[tabId]).forEach((c) => {
      try {
        c.destroy();
      } catch (err) {
        /* ya destruida */
      }
    });
    state.charts[tabId] = [];
    chartLib.pending = chartLib.pending.filter((item) => item.tabId !== tabId);
  }

  /** Junta las gráficas de una pestaña y las monta después de insertar el HTML. */
  function createView(tabId) {
    const items = [];
    return {
      chart(spec) {
        const key = `c${items.length}`;
        items.push({ key, config: spec.config });
        const style = spec.height ? ` style="height:${Number(spec.height)}px"` : '';
        return `<figure class="card chart" data-chart="${key}">` +
          `<figcaption>${esc(spec.title)}</figcaption>` +
          (spec.sub ? `<div class="chart-sub">${esc(spec.sub)}</div>` : '') +
          `<div class="chart-box"${style}><canvas role="img" aria-label="${esc(spec.aria || spec.title)}"></canvas></div>` +
          `<div class="chart-fallback"><p class="chart-fallback-note">Gráfica no disponible: no cargó Chart.js.</p>${spec.fallback || ''}</div>` +
          (spec.after ? `<div class="chart-after">${spec.after}</div>` : '') +
          '</figure>';
      },
      mount(panel) {
        items.forEach((it) => {
          const el = panel.querySelector(`[data-chart="${it.key}"]`);
          if (el) queueChart({ tabId, el, config: it.config });
        });
      },
    };
  }

  function moneyAxis(extra) {
    return Object.assign({
      border: { display: false },
      grid: { color: (ctx) => (ctx.tick && ctx.tick.value === 0 ? COLORS.axis : COLORS.grid) },
      ticks: { display: !state.hide, callback: (v) => fmtMoney(v, { unit: false }) },
    }, extra || {});
  }

  function pctAxis(extra) {
    return Object.assign({
      min: 0, max: 100, border: { display: false }, grid: { color: COLORS.grid },
      ticks: { stepSize: 25, callback: (v) => `${v}%` },
    }, extra || {});
  }

  const toPct100 = (v) => (isNum(v) ? Math.round(v * 1000) / 10 : null);

  function barDataset(label, data, color) {
    return {
      label, data, backgroundColor: color, borderRadius: 4, borderSkipped: 'start',
      maxBarThickness: 24, categoryPercentage: 0.7, barPercentage: 0.9,
    };
  }

  // =====================================================================
  // Pestaña: Bankroll 2026
  // =====================================================================

  function renderBankroll(tab, view) {
    const st = state.data.status;
    const cfg = obj(state.data.config);
    if (!isObj(st)) return panelTitle(tab.label) + empty('No se pudo cargar bankroll_2026_status.json.');
    return [
      panelTitle(tab.label, `Actualizado ${fmtDate(st.generated_at)}`),
      statusCard(st, cfg),
      bankrollKpis(st),
      `<div class="block">${bankrollChart(st, view)}</div>`,
      block('Semana por semana', bankrollTable(st)),
      block('Distribución semanal del presupuesto', distribution(state.data.dist, st)),
      block('Contraste con boletos', contrast(st)),
      block('Lecciones aprendidas 2024/25', lessons()),
    ].join('');
  }

  function statusCard(st, cfg) {
    const level = LEVELS[st.nivel] ? st.nivel : 'verde';
    const stopped = level === 'detenido' || st.estado === 'DETENIDO';
    const lit = stopped ? 'rojo' : level;
    const lamps = ['verde', 'amarillo', 'rojo'].map((l) => `<span class="lamp lamp-${l}${l === lit ? ' on' : ''}"></span>`).join('');
    const pctRaw = toNum(st.pct_del_limite_usado);
    const pct = pctRaw === null ? 0 : Math.min(Math.max(pctRaw, 0), 1);
    const width = fixZero(Math.round(pct * 1000) / 10);
    const estado = st.estado || (stopped ? 'DETENIDO' : 'ACTIVO');
    const rule = st.regla || obj(cfg.stop_loss).rule || '';
    const season = st.season || cfg.season || '';
    return `<section class="card status-card level-${stopped ? 'detenido' : level}" aria-label="Semáforo del stop loss">` +
      '<div class="status-top">' +
      `<div class="traffic" role="img" aria-label="Semáforo en ${esc(LEVELS[level])}">${lamps}</div>` +
      `<div><div class="status-level">${esc(LEVELS[level])}</div>${badge(estado, stopped ? 'stop' : 'good')}</div>` +
      '</div>' +
      `<div><div class="hero-label">Neto acumulado ${esc(season)}</div>` +
      `<div class="hero-value ${isHiddenAmount(st.neto_acumulado_mxn) ? '' : toneClass(st.neto_acumulado_mxn)}">${esc(fmtMoney(st.neto_acumulado_mxn, { signed: true }))}</div></div>` +
      '<div class="meter-wrap">' +
      `<div class="meter" role="progressbar" aria-label="Límite de pérdida usado" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${width}">` +
      `<div class="meter-fill" style="width:${width}%"></div></div>` +
      `<div class="meter-caption">${esc(fmtPct(pct, { digits: 1 }))} del límite usado. ` +
      `Restante antes de parar: <strong>${esc(fmtMoney(st.restante_antes_de_parar_mxn))}</strong></div>` +
      '</div>' +
      (rule ? `<p class="rule"><strong>Regla:</strong> ${esc(maskText(rule))}</p>` : '') +
      levelsLegend(cfg) +
      '</section>';
  }

  function levelsLegend(cfg) {
    const levels = arr(obj(cfg.stop_loss).warning_levels).filter(isObj);
    if (!levels.length) return '';
    const items = levels.map((lv) => {
      const color = LEVEL_COLORS[lv.label] || 'var(--muted)';
      const range = `${fmtMoney(lv.from_net, { unit: false })} a ${fmtMoney(lv.to_net)}`;
      return `<span style="--lv:${color}">${esc(LEVELS[lv.label] || lv.label)}: ${esc(range)}</span>`;
    });
    const max = toNum(obj(cfg.stop_loss).max_net_loss_mxn);
    if (max !== null) items.push(`<span style="--lv:var(--bad)">Detenido: ${esc(fmtMoney(-max))} o menos</span>`);
    return `<div class="levels-legend">${items.join('')}</div>`;
  }

  function bankrollKpis(st) {
    const weeks = arr(st.weeks);
    const limit = toNum(st.limite_perdida_mxn);
    const g = fmtNum(st.semanas_ganadoras);
    const p = fmtNum(st.semanas_perdedoras);
    return '<div class="block kpis kpis-6">' + [
      kpi('Neto acumulado', money(st.neto_acumulado_mxn, { signed: true }),
        `Depósitos ${esc(fmtMoney(st.deposito_total))}, retiros ${esc(fmtMoney(st.retiro_total))}`),
      kpi('Límite de pérdida', esc(fmtMoney(limit === null ? st.limite_perdida_mxn : -limit)), 'Stop loss de la temporada'),
      kpi('Restante antes de parar', esc(fmtMoney(st.restante_antes_de_parar_mxn)),
        `${esc(fmtPct(st.pct_del_limite_usado, { digits: 1 }))} del límite usado`),
      kpi('Semanas capturadas', esc(fmtNum(st.semanas_capturadas)), `de ${weeks.length} en el calendario`),
      kpi('Ganadoras / perdedoras', `<span class="pos">${esc(g)}</span> / <span class="neg">${esc(p)}</span>`, 'semanas con neto a favor / en contra'),
      kpi('Semanas de presupuesto restantes', esc(fmtNum(st.semanas_de_presupuesto_restantes, 1)),
        `a ${esc(fmtMoney(st.presupuesto_semanal_mxn))} por semana`),
    ].join('') + '</div>';
  }

  function bankrollChart(st, view) {
    const weeks = arr(st.weeks).filter(isObj);
    if (!weeks.length) return empty('Sin semanas en el calendario.');
    const limit = toNum(st.limite_perdida_mxn);
    const lastFilled = lastIndex(weeks, (w) => w.filled);
    const builtHidden = weeks.some((w) => w.acumulado === 'oculto');
    let sub = lastFilled < 0
      ? 'Aún no hay semanas capturadas: la línea azul aparece al capturar depósito y retiro.'
      : `Hasta ${weeks[lastFilled].label}. La línea roja punteada es el stop loss.`;
    if (builtHidden) sub = 'Montos ocultos en la publicación: solo se muestra el límite.';
    return view.chart({
      title: 'Neto acumulado por semana',
      sub,
      aria: 'Gráfica de línea del neto acumulado por semana contra el límite de pérdida',
      config: () => bankrollChartConfig(weeks, limit, lastFilled),
      fallback: '<p class="muted small">Los datos están en la tabla semana por semana.</p>',
    });
  }

  function bankrollChartConfig(weeks, limit, lastFilled) {
    const labels = weeks.map((w) => shortWeek(w.label));
    const acc = weeks.map((w, i) => (i <= lastFilled && isNum(w.acumulado) ? w.acumulado : null));
    const datasets = [{
      label: 'Neto acumulado', data: acc, borderColor: COLORS.series[0], backgroundColor: COLORS.series[0],
      borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: COLORS.surface, pointBorderWidth: 2,
      tension: 0, spanGaps: false,
    }];
    if (limit !== null) {
      datasets.push({
        label: 'Límite de pérdida', data: labels.map(() => -limit), borderColor: COLORS.critical,
        backgroundColor: COLORS.critical, borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, pointHoverRadius: 0, pointHitRadius: 0,
      });
    }
    return {
      type: 'line',
      data: { labels, datasets },
      options: {
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { grid: { display: false }, border: { color: COLORS.axis }, ticks: { maxRotation: 0, autoSkipPadding: 6 } },
          y: moneyAxis(limit !== null ? { suggestedMin: -limit * 1.1, suggestedMax: limit * 0.25 } : {}),
        },
        plugins: {
          tooltip: {
            filter: (item) => item.parsed.y !== null,
            callbacks: {
              title: (items) => {
                const w = weeks[items[0].dataIndex] || {};
                return `${w.label || ''}${w.dates ? ` (${w.dates})` : ''}`;
              },
              label: (ctx) => `${ctx.dataset.label}: ${fmtMoney(ctx.parsed.y, { signed: true })}`,
            },
          },
        },
      },
    };
  }

  function bankrollTable(st) {
    const weeks = arr(st.weeks).filter(isObj);
    if (!weeks.length) return empty('Sin semanas.');
    const rows = weeks.map((w) => ({
      cls: w.filled ? '' : 'dim',
      cells: [
        `<strong>${esc(w.label || NA)}</strong>${w.note ? `<span class="cell-note">${esc(w.note)}</span>` : ''}`,
        `<span class="num">${esc(w.dates || NA)}</span>`,
        numCell(esc(fmtMoney(w.deposito, { unit: false }))),
        numCell(esc(fmtMoney(w.retiro, { unit: false }))),
        numCell(money(w.neto, { signed: true, unit: false })),
        numCell(money(w.acumulado, { signed: true, unit: false })),
        w.filled ? badge('capturada', 'good') : badge('sin capturar', 'neutral'),
      ],
    }));
    const head = ['Semana', 'Fechas', th('Depósito', 'r'), th('Retiro', 'r'), th('Neto', 'r'), th('Acumulado', 'r'), 'Estado'];
    return table(head, rows, 'Tabla semanal del bankroll') +
      '<p class="block-note" style="margin-top:8px">Montos en MXN. Neto = retiros menos depósitos.</p>';
  }

  function distribution(dist, st) {
    const buckets = arr(obj(dist).buckets).filter(isObj);
    if (!buckets.length) return empty('Sin distribución capturada.');
    const total = toNum(obj(dist).presupuesto_semanal_mxn) !== null ? dist.presupuesto_semanal_mxn : st.presupuesto_semanal_mxn;
    const totalNum = toNum(total);
    const shareOf = (b) => (isNum(b.share) ? b.share : (isNum(b.mxn) && totalNum ? b.mxn / totalNum : 0));
    const color = (i) => COLORS.series[i % COLORS.series.length];
    const segments = buckets.map((b, i) =>
      `<span style="flex:${shareOf(b)} 1 0%;background:${color(i)}" title="${esc(b.name)}: ${esc(fmtPct(shareOf(b)))}"></span>`).join('');
    const summary = buckets.map((b) => `${b.name} ${fmtPct(shareOf(b))}`).join(', ');
    const items = buckets.map((b, i) =>
      `<li><span class="swatch" style="background:${color(i)}"></span><div>` +
      `<div class="bucket-main"><span class="bucket-name">${esc(b.name || NA)}</span>` +
      `<span class="num">${esc(fmtMoney(b.mxn))}</span><span class="muted small">${esc(fmtPct(shareOf(b)))}</span></div>` +
      `${b.descripcion ? `<div class="muted small">${esc(b.descripcion)}</div>` : ''}</div></li>`).join('');
    const rest = toNum(obj(dist).restante);
    return '<div class="card">' +
      `<div class="bucket-main"><span class="muted small">Presupuesto semanal</span><strong class="num">${esc(fmtMoney(total))}</strong></div>` +
      `<div class="stack" role="img" aria-label="Reparto: ${esc(summary)}">${segments}</div>` +
      `<ul class="bucket-list">${items}</ul>` +
      (rest ? `<p class="note">Sin asignar: ${esc(fmtMoney(rest))}</p>` : '') +
      (dist.source ? `<p class="note">Fuente: ${esc(dist.source)}</p>` : '') +
      '</div>';
  }

  function contrast(st) {
    const c = obj(st.contraste_boletos);
    if (!Object.keys(c).length) return empty('Sin boletos para contrastar.');
    const captured = Number(st.semanas_capturadas) > 0;
    const ticketsNet = toNum(c.neto_mxn);
    const ledgerNet = toNum(st.neto_acumulado_mxn);
    let warning = '';
    if (!captured && Number(c.n_liquidados) > 0) {
      warning = banner('warn', 'El ledger no tiene semanas capturadas',
        'Ya hay boletos liquidados, pero el ledger semanal sigue vacío. Captura depósito y retiro de esas semanas para que el stop loss sea real.');
    } else if (ticketsNet !== null && ledgerNet !== null && Math.round(ticketsNet - ledgerNet) !== 0) {
      warning = `<p class="note">Diferencia boletos menos ledger: ${esc(fmtMoney(ticketsNet - ledgerNet, { signed: true }))}. Puede haber boletos sin capturar o depósitos sin apostar.</p>`;
    }
    return '<div class="kpis">' +
      kpi('Boletos liquidados', esc(fmtNum(c.n_liquidados)), 'extraídos de capturas') +
      kpi('Neto según boletos', money(c.neto_mxn, { signed: true }), 'apuestas gratis cuentan como 0') +
      kpi('Neto según ledger', money(st.neto_acumulado_mxn, { signed: true }), 'fuente de verdad') +
      '</div>' +
      (c.nota ? `<p class="note">${esc(c.nota)}</p>` : '') +
      (warning ? `<div style="margin-top:10px">${warning}</div>` : '');
  }

  function lessons() {
    const fromFiles = [state.data.b2024, state.data.b2025].map((b) => arr(obj(b).lessons_learned));
    const fromHistory = arr(obj(state.data.history).seasons).map((s) => arr(obj(s).lessons_learned));
    const items = uniq(fromFiles.concat(fromHistory).flat().filter((t) => typeof t === 'string' && t.trim()));
    if (!items.length) return empty('Sin lecciones registradas.');
    return `<div class="card">${markList(items)}</div>`;
  }

  // =====================================================================
  // Pestaña: Mis tendencias
  // =====================================================================

  function renderTendencias(tab, view) {
    const a = state.data.analysis;
    const bets = state.data.bets;
    const tickets = arr(obj(bets).tickets).filter(isObj);
    if (!isObj(a)) {
      return panelTitle(tab.label) + empty('No se pudo cargar my_bets_analysis.json.') +
        block('Mis boletos', ticketsList(tickets));
    }
    return [
      panelTitle(tab.label, `Actualizado ${fmtDate(a.generated_at)}`),
      sampleWarning(a),
      block('Resumen global', globalKpis(a), { extra: sampleBadge(obj(a.global).muestra_chica) }),
      `<div class="block grid cols-2">${categoryChart(a, view)}${legsChart(a, view)}</div>`,
      `<div class="block">${calibrationChart(a, view)}</div>`,
      block('Desglose de boletos', breakdown(a), { note: 'Montos en MXN. Una apuesta gratis cuenta como 0 invertido.' }),
      block('La leg que me mata', killerLeg(a)),
      '<div class="block grid cols-3">' +
        ruleCard('Qué sí', a.que_si, 'si', 'Todavía no hay categorías con buen hit rate y muestra suficiente.') +
        ruleCard('Qué no', a.que_no, 'no', 'Todavía no hay categorías claramente perdedoras con muestra suficiente.') +
        ruleCard('Muestra insuficiente', a.muestra_insuficiente, 'warn', 'Nada pendiente.') +
      '</div>',
      block('Mis boletos', ticketsList(tickets), { extra: `<span class="muted small">${tickets.length} en total</span>` }),
    ].join('');
  }

  function sampleWarning(a) {
    const parts = [];
    if (a.advertencia_muestra) parts.push(String(a.advertencia_muestra));
    if (Number(a.n_no_validados) > 0) {
      parts.push(`${a.n_no_validados} de ${fmtNum(a.n_boletos_total)} boletos todavía no están validados contra la captura.`);
    }
    if (Number(a.n_boletos_open) > 0) parts.push(`${a.n_boletos_open} boleto(s) abiertos no cuentan en las métricas.`);
    if (!parts.length) return '';
    return `<div class="banner banner-warn" role="status"><strong>Ojo con la muestra</strong>${parts.map((p) => `<p>${esc(p)}</p>`).join('')}</div>`;
  }

  function globalKpis(a) {
    const g = obj(a.global);
    return '<div class="kpis kpis-6">' + [
      kpi('Boletos liquidados', esc(fmtNum(g.n)), `${esc(fmtNum(a.n_boletos_total))} capturados en total`),
      kpi('Invertido', money(g.invertido_mxn), 'sin contar apuestas gratis'),
      kpi('Cobrado', money(g.cobrado_mxn), 'pagos recibidos'),
      kpi('Profit', money(g.profit_mxn, { signed: true }), 'cobrado menos invertido'),
      kpi('ROI', pctSigned(g.roi), 'profit / invertido'),
      kpi('Hit rate', esc(fmtPct(g.hit_rate)), `${esc(fmtNum(g.ganados))} de ${esc(fmtNum(g.n))} boletos ganados`),
    ].join('') + '</div>';
  }

  function categoryChart(a, view) {
    const cats = Object.entries(obj(a.por_categoria_leg))
      .filter(([, v]) => isObj(v))
      .map(([key, v]) => Object.assign({ key, label: v.label || catLabel(key) }, v))
      .sort((x, y) => (Number(y.n) || 0) - (Number(x.n) || 0) || String(x.label).localeCompare(String(y.label)));
    if (!cats.length) return `<div class="card"><h3>Hit rate por categoría de leg</h3>${empty('Sin legs calificadas.')}</div>`;
    const tbl = table(['Categoría', th('n', 'r'), th('G-P', 'r'), th('Hit rate', 'r'), ''], cats.map((c) => [
      esc(c.label), numCell(esc(fmtNum(c.n))), numCell(`${esc(fmtNum(c.wins))}-${esc(fmtNum(c.losses))}`),
      numCell(esc(fmtPct(c.hit_rate))), sampleBadge(c.muestra_chica),
    ]), 'Hit rate por categoría');
    return view.chart({
      title: 'Hit rate por categoría de leg',
      sub: 'Legs calificadas (ganó o perdió). n = número de legs.',
      height: Math.max(170, cats.length * 42 + 50),
      config: () => ({
        type: 'bar',
        data: {
          labels: cats.map((c) => `${c.label} (n=${fmtNum(c.n)})`),
          datasets: [Object.assign(barDataset('Hit rate', cats.map((c) => toPct100(c.hit_rate)), COLORS.series[0]), { categoryPercentage: 0.8 })],
        },
        options: {
          indexAxis: 'y',
          scales: { x: pctAxis(), y: { grid: { display: false }, border: { color: COLORS.axis }, ticks: { color: COLORS.text2 } } },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const c = cats[ctx.dataIndex];
                  return `Hit rate ${fmtPct(c.hit_rate)} (${fmtNum(c.wins)} de ${fmtNum(c.n)})${c.muestra_chica ? ', muestra chica' : ''}`;
                },
              },
            },
          },
        },
      }),
      after: tbl,
    });
  }

  function legsChart(a, view) {
    const rows = Object.entries(obj(a.por_legs))
      .filter(([, v]) => isObj(v))
      .sort((x, y) => rankIn(LEGS_ORDER, x[0]) - rankIn(LEGS_ORDER, y[0]))
      .map(([k, v]) => Object.assign({ k }, v));
    if (!rows.length) return `<div class="card"><h3>Boletos por número de legs</h3>${empty('Sin boletos liquidados.')}</div>`;
    const legWord = (k) => (k === '1' ? '1 leg' : `${k} legs`);
    const tbl = table(['Legs', th('n', 'r'), th('Hit rate', 'r'), th('Prob. implícita', 'r'), th('ROI', 'r'), ''], rows.map((r) => [
      esc(legWord(r.k)), numCell(esc(fmtNum(r.n))), numCell(esc(fmtPct(r.hit_rate))),
      numCell(esc(fmtPct(r.prob_implicita_prom, { digits: 1 }))), numCell(pctSigned(r.roi)), sampleBadge(r.muestra_chica),
    ]), 'Boletos por número de legs');
    return view.chart({
      title: 'Boletos por número de legs',
      sub: 'Hit rate real contra la probabilidad implícita promedio del momio.',
      config: () => ({
        type: 'bar',
        data: {
          labels: rows.map((r) => `${legWord(r.k)} (n=${fmtNum(r.n)})`),
          datasets: [
            barDataset('Hit rate real', rows.map((r) => toPct100(r.hit_rate)), COLORS.series[0]),
            barDataset('Prob. implícita prom.', rows.map((r) => toPct100(r.prob_implicita_prom)), COLORS.series[1]),
          ],
        },
        options: {
          scales: { x: { grid: { display: false }, border: { color: COLORS.axis } }, y: pctAxis() },
          plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y === null ? NA : `${fmtNum(ctx.parsed.y, 1)}%`}` } } },
        },
      }),
      after: tbl,
    });
  }

  function calibrationChart(a, view) {
    const bins = arr(a.calibracion).filter(isObj);
    if (!bins.length) return `<div class="card"><h3>Calibración</h3>${empty('Sin legs con momio para calibrar.')}</div>`;
    const tbl = table(['Rango de prob. implícita', th('n', 'r'), th('Prob. implícita', 'r'), th('Hit rate real', 'r'), th('Diferencia', 'r')], bins.map((b) => {
      const diff = isNum(b.hit_rate) && isNum(b.prob_implicita_prom) ? b.hit_rate - b.prob_implicita_prom : null;
      return [esc(b.bin), numCell(esc(fmtNum(b.n))), numCell(esc(fmtPct(b.prob_implicita_prom, { digits: 1 }))),
        numCell(esc(fmtPct(b.hit_rate, { digits: 1 }))), numCell(`${pctSigned(diff)}${Number(b.n) < 10 ? ` ${sampleBadge(true)}` : ''}`)];
    }), 'Calibración');
    return view.chart({
      title: 'Calibración de legs',
      sub: 'Si estás bien calibrado, las dos barras de cada rango se parecen. Solo legs con momio.',
      config: () => ({
        type: 'bar',
        data: {
          labels: bins.map((b) => `${b.bin} (n=${fmtNum(b.n)})`),
          datasets: [
            barDataset('Hit rate real', bins.map((b) => toPct100(b.hit_rate)), COLORS.series[0]),
            barDataset('Prob. implícita prom.', bins.map((b) => toPct100(b.prob_implicita_prom)), COLORS.series[1]),
          ],
        },
        options: {
          scales: { x: { grid: { display: false }, border: { color: COLORS.axis } }, y: pctAxis() },
          plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y === null ? NA : `${fmtNum(ctx.parsed.y, 1)}%`}` } } },
        },
      }),
      after: tbl,
    });
  }

  function groupTable(groups, labelFn, order, label) {
    const entries = Object.entries(obj(groups)).filter(([, v]) => isObj(v));
    if (order) entries.sort((x, y) => rankIn(order, x[0]) - rankIn(order, y[0]));
    if (!entries.length) return empty('Sin boletos en este grupo.');
    const rows = entries.map(([k, v]) => [
      `${esc(labelFn ? labelFn(k) : k)} ${sampleBadge(v.muestra_chica)}`,
      numCell(esc(fmtNum(v.n))),
      numCell(esc(fmtMoney(v.invertido_mxn, { unit: false }))),
      numCell(esc(fmtMoney(v.cobrado_mxn, { unit: false }))),
      numCell(money(v.profit_mxn, { signed: true, unit: false })),
      numCell(pctSigned(v.roi)),
      numCell(`${esc(fmtPct(v.hit_rate))} <span class="muted">(${esc(fmtNum(v.ganados))}/${esc(fmtNum(v.n))})</span>`),
    ]);
    const head = ['Grupo', th('n', 'r'), th('Invertido', 'r'), th('Cobrado', 'r'), th('Profit', 'r'), th('ROI', 'r'), th('Hit rate', 'r')];
    return table(head, rows, label);
  }

  function breakdown(a) {
    const parts = [
      ['Por casa', groupTable(a.por_casa, bookName, null, 'Por casa')],
      ['Por horario', groupTable(a.por_horario, capitalize, HORARIO_ORDER, 'Por horario')],
      ['Siguiendo canal vs propio', groupTable(a.por_origen, capitalize, ['siguiendo canal', 'propio'], 'Por origen')],
      ['Por tipo de boleto', groupTable(a.por_tipo, typeLabel, null, 'Por tipo')],
      ['Boosts y apuestas gratis', groupTable({ Boosts: a.boosts, 'Apuestas gratis': a.apuestas_gratis }, null, null, 'Boosts y apuestas gratis')],
    ];
    return parts.map(([title, html]) => `<h3 class="sub-title">${esc(title)}</h3>${html}`).join('');
  }

  function killerLeg(a) {
    const k = obj(a.leg_que_me_mata);
    const lost = toNum(k.parlays_perdidos);
    const one = toNum(k.perdidos_por_una_sola_leg);
    if (lost === null) return empty('Sin datos de parlays perdidos.');
    const culprits = Object.entries(obj(k.categoria_culpable)).filter(([, n]) => isNum(n)).sort((x, y) => y[1] - x[1]);
    const max = Math.max(1, ...culprits.map(([, n]) => n));
    const headline = lost > 0
      ? `<p><strong class="num">${esc(fmtNum(one))} de ${esc(fmtNum(lost))}</strong> combinadas perdidas se cayeron por una sola leg` +
        `${one !== null ? ` (${esc(fmtPct(one / lost))})` : ''}.</p>`
      : '<p>Todavía no hay combinadas perdidas.</p>';
    const list = culprits.map(([cat, n]) =>
      `<li><div class="bar-row"><span>${esc(catLabel(cat))}</span><span class="num">${esc(fmtNum(n))}</span></div>` +
      `<div class="bar-track"><div class="bar-fill" style="width:${Math.round((n / max) * 100)}%"></div></div></li>`).join('');
    return `<div class="card">${headline}` +
      (culprits.length ? `<h3 class="sub-title">Categoría de la leg que falló</h3><ul class="bar-list">${list}</ul>` : '') +
      (lost > 0 && lost < 10 ? `<p class="note">${sampleBadge(true)} Con menos de 10 combinadas perdidas esto es solo una pista.</p>` : '') +
      '</div>';
  }

  function ruleCard(title, items, kind, emptyText) {
    const list = arr(items).filter((t) => typeof t === 'string' && t.trim());
    return `<div class="card"><h3 class="card-title">${esc(title)} <span class="muted small">(${list.length})</span></h3>` +
      (list.length ? markList(list, kind) : `<p class="muted small">${esc(emptyText)}</p>`) + '</div>';
  }

  function ticketsList(tickets) {
    if (!tickets.length) return empty('Todavía no hay boletos capturados.');
    const sorted = tickets.slice().sort((x, y) => String(y.placed_at || '').localeCompare(String(x.placed_at || '')));
    return `<div class="grid cols-2">${sorted.map(ticketCard).join('')}</div>`;
  }

  function ticketCard(t) {
    const status = TICKET_STATUS[t.status] || [t.status || 'sin estado', 'neutral'];
    let follow = '';
    if (t.followed_channel) follow = badge(typeof t.followed_channel === 'string' ? `siguiendo canal: ${t.followed_channel}` : 'siguiendo canal', 'info');
    const badges = [
      t.boost ? badge('boost', 'accent') : '',
      t.free_bet ? badge('apuesta gratis', 'info') : '',
      t.validated === false ? badge('No validado', 'warn', 'Pendiente validar contra la captura') : '',
      follow,
      t.book_confidence === 'inferido' ? badge('casa inferida', 'neutral', 'La casa se infirió por el formato de la captura') : '',
    ].join('');
    const beforeBoost = t.boost && toNum(t.odds_before_boost_american) !== null
      ? ` <span class="muted small">(antes ${esc(fmtAmerican(t.odds_before_boost_american))})</span>` : '';
    const stake = esc(fmtMoney(t.stake_mxn)) + (t.free_bet ? ' <span class="muted small">(gratis)</span>' : '');
    const legs = arr(t.legs).filter(isObj);
    const facts = [
      ['Fecha', esc(fmtDate(t.placed_at))],
      ['Tipo', esc(typeLabel(t.type))],
      ['Legs', esc(fmtNum(toNum(t.legs_count) !== null ? t.legs_count : legs.length))],
      ['Semana', t.week ? `W${esc(pad2(t.week))}` : NA],
      ['Stake', stake],
      ['Momio', `${oddsPair(t.odds_american, t.odds_decimal)}${beforeBoost}`],
      ['Cobrado', esc(fmtMoney(t.payout_mxn))],
      ['Boleto', `<span class="num">${esc(t.ticket_id || NA)}</span>`],
    ].map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('');
    return '<article class="card ticket">' +
      `<div class="ticket-head"><div><div class="ticket-title">${esc(bookName(t.book))}</div>` +
      `<div class="muted small">${esc(fmtDate(t.placed_at))}</div></div>${badge(status[0], status[1])}</div>` +
      (badges ? `<div class="badges" style="margin-top:8px">${badges}</div>` : '') +
      `<dl class="facts">${facts}</dl>` +
      (t.notes ? `<p class="note">${esc(t.notes)}</p>` : '') +
      (legs.length
        ? `<details><summary>Ver legs (${legs.length})</summary><ul class="legs">${legs.map(legItem).join('')}</ul></details>`
        : (t.legs_visible === false ? '<p class="note">Las legs no se ven en la captura.</p>' : '')) +
      '</article>';
  }

  function oddsPair(american, decimal) {
    const am = toNum(american) !== null ? fmtAmerican(american) : null;
    const dec = toNum(decimal) !== null ? fmtDecimal(decimal) : null;
    if (!am && !dec) return '<span class="muted">sin momio</span>';
    return `<span class="num">${esc(am || dec)}</span>${am && dec ? ` <span class="muted small">(${esc(dec)})</span>` : ''}`;
  }

  function legItem(l) {
    const res = RESULTS[l.result] || ['Pendiente', 'neutral'];
    const meta = [l.game, catLabel(l.category)].filter(Boolean).map(esc).join(' · ');
    const src = l.source && l.source !== 'propio' ? ` · ${esc(l.source)}` : '';
    return `<li><div class="leg-top"><span class="leg-sel">${esc(l.selection || NA)}</span>${badge(res[0], res[1])}</div>` +
      `<div class="muted small">${meta} · momio ${oddsPair(l.odds_american, l.odds_decimal)}${src}</div>` +
      (l.notes ? `<p class="note">${esc(l.notes)}</p>` : '') + '</li>';
  }

  // =====================================================================
  // Pestaña: Historial 24/25
  // =====================================================================

  function renderHistorial(tab, view) {
    const h = obj(state.data.history);
    const seasons = arr(h.seasons).filter(isObj).sort((x, y) => x.season - y.season);
    if (!seasons.length) return panelTitle(tab.label) + empty('No se pudo cargar history/analysis.json.');
    return [
      panelTitle(tab.label, `Temporadas ${seasons.map((s) => s.season).join(' y ')}`),
      stopNotes(seasons),
      seasonHeroes(seasons, h.combined),
      block('Comparativa global', compareTable(seasons)),
      `<div class="block">${historyChart(seasons, view)}</div>`,
      block('Por fase', splitTable(seasons, 'por_fase', PHASES, 'Fase')),
      block('Temporada regular por tramo', splitTable(seasons, 'temporada_regular_por_tramo', TRAMOS, 'Tramo')),
      block('Por mes', monthsTable(seasons)),
      block('Rachas', streaksTable(seasons)),
      block('Reglas con datos', rulesWithData(h.reglas_con_datos)),
    ].join('');
  }

  function seasonLedger(season) {
    return obj(state.data[`b${season}`]);
  }

  function stopNotes(seasons) {
    return seasons.filter((s) => s.stopped_after).map((s) => {
      const reason = seasonLedger(s.season).stop_reason;
      return banner('info', `${s.season} se detuvo después de ${s.stopped_after}`,
        `${reason ? `${reason}. ` : ''}Las semanas siguientes aparecen en 0 y la línea de la gráfica se vuelve punteada.`);
    }).join('');
  }

  function seasonHeroes(seasons, combined) {
    const cards = seasons.map((s) => {
      const g = obj(s.global);
      return '<div class="card">' +
        `<div class="kpi-label">Temporada ${esc(s.season)}</div>` +
        `<div class="hero-value season-hero">${money(g.neto, { signed: true })}</div>` +
        `<div class="small">ROI ${pctSigned(g.roi)}, ${esc(fmtNum(g.n_semanas_jugadas))} semanas jugadas</div>` +
        (s.stopped_after ? `<div style="margin-top:6px">${badge(`detenida tras ${s.stopped_after}`, 'warn')}</div>` : '') +
        '</div>';
    }).join('');
    const c = obj(combined);
    const comb = Object.keys(c).length
      ? `<p class="note">Combinado: depositado ${esc(fmtMoney(c.deposito))}, retirado ${esc(fmtMoney(c.retiro))}, neto ${money(c.neto, { signed: true })}.</p>`
      : '';
    return `<div class="block grid-2">${cards}</div>${comb}`;
  }

  function weekNet(season, label) {
    const hit = arr(season.acumulado).find((a) => isObj(a) && a.label === label);
    return hit ? hit.neto : null;
  }

  function weekWithNet(season, label) {
    if (!label) return NA;
    const net = weekNet(season, label);
    return `${esc(label)}${net !== null ? ` <span class="muted">(${money(net, { signed: true, unit: false })})</span>` : ''}`;
  }

  function compareTable(seasons) {
    const G = (s) => obj(s.global);
    const metrics = [
      ['Neto', (s) => money(G(s).neto, { signed: true })],
      ['ROI', (s) => pctSigned(G(s).roi)],
      ['Depositado', (s) => money(G(s).deposito)],
      ['Retirado', (s) => money(G(s).retiro)],
      ['Semanas jugadas', (s) => esc(fmtNum(G(s).n_semanas_jugadas))],
      ['Semanas ganadoras', (s) => `${esc(fmtNum(G(s).semanas_ganadoras))} de ${esc(fmtNum(G(s).n_semanas_jugadas))}`],
      ['Hit rate semanal', (s) => esc(fmtPct(G(s).hit_rate_semanal))],
      ['Semanas sin retiro', (s) => esc(fmtNum(G(s).semanas_sin_retiro))],
      ['Promedio neto por semana', (s) => money(G(s).promedio_neto_semana, { signed: true })],
      ['Mejor semana', (s) => weekWithNet(s, G(s).mejor_semana)],
      ['Peor semana', (s) => weekWithNet(s, G(s).peor_semana)],
      ['Mejor acumulado', (s) => money(s.mejor_acumulado, { signed: true })],
      ['Peor acumulado', (s) => money(s.peor_acumulado, { signed: true })],
    ];
    const head = ['Métrica'].concat(seasons.map((s) => th(String(s.season), 'r')));
    const rows = metrics.map(([label, fn]) => [esc(label)].concat(seasons.map((s) => numCell(fn(s)))));
    return table(head, rows, 'Comparativa global por temporada');
  }

  function historyChart(seasons, view) {
    const series = seasons.filter((s) => Array.isArray(s.acumulado) && s.acumulado.length);
    if (!series.length) return `<div class="card"><h3>Acumulado por temporada</h3>${empty('Montos ocultos en la publicación: no hay acumulado para graficar.')}</div>`;
    const maxLen = Math.max(...series.map((s) => s.acumulado.length));
    const labels = Array.from({ length: maxLen }, (_, i) => String(i + 1));
    const stopIdx = (s) => (s.stopped_after ? s.acumulado.findIndex((a) => isObj(a) && a.label === s.stopped_after) : -1);
    const fallbackRows = labels.map((l, i) => [esc(l)].concat(series.map((s) => {
      const a = obj(s.acumulado[i]);
      return numCell(a.label ? `${money(a.acumulado, { signed: true, unit: false })} <span class="muted">${esc(shortWeek(a.label))}</span>` : '');
    })));
    return view.chart({
      title: 'Acumulado por temporada',
      sub: 'Eje x: número de semana en el archivo (incluye pretemporada). Pasa el dedo para ver la semana real.',
      aria: `Gráfica de línea del acumulado de ${series.map((s) => s.season).join(' y ')}`,
      config: () => ({
        type: 'line',
        data: {
          labels,
          datasets: series.map((s, i) => {
            const stop = stopIdx(s);
            const color = COLORS.series[i % COLORS.series.length];
            return {
              label: String(s.season),
              data: s.acumulado.map((a) => (isObj(a) && isNum(a.acumulado) ? a.acumulado : null)),
              borderColor: color, backgroundColor: color, borderWidth: 2, tension: 0,
              pointRadius: (ctx) => (stop >= 0 && ctx.dataIndex > stop ? 0 : 3),
              pointHoverRadius: 5, pointBorderColor: COLORS.surface, pointBorderWidth: 1.5,
              segment: { borderDash: (ctx) => (stop >= 0 && ctx.p0DataIndex >= stop ? [4, 4] : undefined) },
            };
          }),
        },
        options: {
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: { grid: { display: false }, border: { color: COLORS.axis }, ticks: { maxRotation: 0, autoSkipPadding: 6 }, title: { display: true, text: 'Semana (índice)', color: COLORS.muted } },
            y: moneyAxis(),
          },
          plugins: {
            tooltip: {
              filter: (item) => item.parsed.y !== null,
              callbacks: {
                title: (items) => `Semana ${items[0].label}`,
                label: (ctx) => {
                  const s = series[ctx.datasetIndex];
                  const a = obj(s.acumulado[ctx.dataIndex]);
                  return `${s.season} (${a.label || NA}): ${fmtMoney(ctx.parsed.y, { signed: true })}`;
                },
              },
            },
          },
        },
      }),
      fallback: table(['#'].concat(series.map((s) => th(String(s.season), 'r'))), fallbackRows, 'Acumulado por semana'),
    });
  }

  function splitTable(seasons, key, defs, firstLabel) {
    const head1 = [{ html: esc(firstLabel), rowspan: 2 }].concat(seasons.map((s) => ({ html: esc(s.season), colspan: 3, cls: 'group' })));
    const head2 = seasons.flatMap(() => [th('Neto', 'r sep'), th('ROI', 'r'), th('Ganadoras / jugadas', 'r')]);
    const rows = defs.map(([k, label]) => [esc(label)].concat(seasons.flatMap((s) => {
      const v = obj(obj(s[key])[k]);
      if (!Number(v.n_semanas_jugadas)) return [{ html: '<span class="muted">sin jugar</span>', colspan: 3, cls: 'sep' }];
      return [
        numCell(money(v.neto, { signed: true, unit: false }), 'sep'),
        numCell(pctSigned(v.roi)),
        numCell(`${esc(fmtNum(v.semanas_ganadoras))} / ${esc(fmtNum(v.n_semanas_jugadas))}`),
      ];
    })));
    return table([head1, head2], rows, firstLabel) + '<p class="block-note" style="margin-top:8px">Neto en MXN.</p>';
  }

  function monthsTable(seasons) {
    const months = uniq(seasons.flatMap((s) => arr(s.meses).filter(isObj).map((m) => m.month)));
    if (!months.length) return empty('Sin datos mensuales.');
    const head1 = [{ html: 'Mes', rowspan: 2 }].concat(seasons.map((s) => ({ html: esc(s.season), colspan: 2, cls: 'group' })));
    const head2 = seasons.flatMap(() => [th('Neto', 'r sep'), th('ROI', 'r')]);
    const rows = months.map((m) => [esc(m)].concat(seasons.flatMap((s) => {
      const v = arr(s.meses).find((x) => isObj(x) && x.month === m);
      if (!v || (!toNum(v.deposito) && !toNum(v.retiro) && v.deposito !== 'oculto')) return [{ html: '<span class="muted">sin jugar</span>', colspan: 2, cls: 'sep' }];
      return [numCell(money(v.neto, { signed: true, unit: false }), 'sep'), numCell(pctSigned(v.roi))];
    })));
    return table([head1, head2], rows, 'Por mes') + '<p class="block-note" style="margin-top:8px">Neto en MXN.</p>';
  }

  function streaksTable(seasons) {
    const R = (s) => obj(s.rachas);
    const head = ['Métrica'].concat(seasons.map((s) => th(String(s.season), 'r')));
    const rows = [
      ['Máx. semanas perdedoras seguidas', (s) => esc(fmtNum(R(s).max_semanas_perdedoras_seguidas))],
      ['Peor drawdown en racha', (s) => money(R(s).peor_drawdown_en_racha, { signed: true })],
    ].map(([label, fn]) => [esc(label)].concat(seasons.map((s) => numCell(fn(s)))));
    return table(head, rows, 'Rachas');
  }

  function rulesWithData(list) {
    const items = arr(list).filter((t) => typeof t === 'string' && t.trim()).map(maskText);
    return items.length ? `<div class="card">${markList(items)}</div>` : empty('Sin reglas derivadas todavía.');
  }

  // =====================================================================
  // Pestaña: Semana N
  // =====================================================================

  function weekFilePath(w) {
    const file = String(w.file || '');
    return /^[\w\-./]+\.json$/.test(file) && !file.includes('..') && !file.startsWith('/') ? `data/${file}` : null;
  }

  async function renderWeek(tab, view) {
    const w = tab.week;
    let d = state.weekData[tab.id];
    if (!d) {
      const path = weekFilePath(w);
      d = path ? await getJSON(path) : null;
      if (isObj(d)) state.weekData[tab.id] = d;
    }
    if (!isObj(d)) return panelTitle(tab.label) + banner('bad', 'No se pudo cargar la semana', `Archivo: data/${w.file || NA}`);
    const picks = arr(d.picks).filter(isObj);
    const sources = arr(d.sources).filter(isObj);
    const sub = `Temporada ${d.season || w.season}, generado ${fmtDate(d.generated_at || w.generated_at)}. ` +
      `${picks.length} pick(s) de ${sources.length} video(s).`;
    let statusBanner = '';
    if (d.status === 'pendiente_transcripcion') statusBanner = banner('warn', 'Pendiente de transcripción', d.status_note);
    else if (d.status_note) statusBanner = banner('info', 'Nota', d.status_note);
    return [
      panelTitle(`Semana ${d.week || w.week}`, sub),
      statusBanner,
      block('Videos fuente', sourcesList(sources)),
      consensusBlock(d),
      block('Picks', picksSection(tab, picks, d)),
      block('Insights del video', insightsList(d.insights)),
      block('Récord del canal', recordSection(d), { note: 'Unidades a 1 u por pick: si gana suma el momio decimal menos 1, si pierde resta 1.' }),
    ].join('');
  }

  function sourcesList(sources) {
    if (!sources.length) return empty('Sin videos registrados para esta semana.');
    const items = sources.map((s) => {
      const url = safeUrl(s.url);
      const title = esc(s.title || s.video_id || 'Video');
      const method = s.transcript_method ? (TRANSCRIPT_METHODS[s.transcript_method] || s.transcript_method) : null;
      const meta = [
        s.channel,
        s.published ? `publicado ${fmtDate(s.published, false)}` : 'fecha sin dato',
        method ? `transcripción: ${method}` : null,
      ].filter(Boolean).map(esc).join(' · ');
      return `<li>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title}` +
        `<div class="muted small">${meta} ${method ? '' : badge('sin transcripción', 'warn')}</div></li>`;
    }).join('');
    return `<div class="card"><ul class="sources">${items}</ul></div>`;
  }

  function consensusBlock(d) {
    const list = arr(d.consensus).filter(isObj);
    if (!list.length) return '';
    const items = list.map((c) => {
      const channels = arr(c.channels);
      return '<div class="consensus-item">' +
        `<div class="pick-game">${esc(c.game || NA)}</div><div class="pick-sel">${esc(c.selection || NA)}</div>` +
        `<div class="badges" style="margin-top:6px">${badge(`${channels.length} canales`, 'good')}${channels.map((ch) => badge(ch, 'info')).join('')}</div>` +
        '</div>';
    }).join('');
    return block('Consenso', `<div class="card">${items}</div>`, { note: 'Mismo partido y misma selección en 2 o más canales.' });
  }

  function picksSection(tab, picks, d) {
    if (!picks.length) {
      return empty(d.status === 'pendiente_transcripcion'
        ? 'Todavía no hay picks: faltan las transcripciones de los videos.'
        : 'Esta semana no tiene picks.');
    }
    const f = state.filters[tab.id] || (state.filters[tab.id] = { channel: '', category: '', q: '' });
    const channels = uniq(picks.map((p) => p.channel).filter(Boolean)).sort();
    const cats = uniq(picks.map((p) => p.category).filter(Boolean)).sort((x, y) => catLabel(x).localeCompare(catLabel(y)));
    const opt = (value, label, current) => `<option value="${esc(value)}"${value === current ? ' selected' : ''}>${esc(label)}</option>`;
    return '<div class="filters" data-filters>' +
      `<label class="field">Canal<select data-f="channel">${opt('', 'Todos los canales', f.channel)}${channels.map((c) => opt(c, c, f.channel)).join('')}</select></label>` +
      `<label class="field">Categoría<select data-f="category">${opt('', 'Todas las categorías', f.category)}${cats.map((c) => opt(c, catLabel(c), f.category)).join('')}</select></label>` +
      `<label class="field">Buscar<input type="search" data-f="q" placeholder="Equipo, jugador o texto" value="${esc(f.q)}" autocomplete="off"></label>` +
      '</div><div class="filter-count" data-count aria-live="polite"></div><div class="grid cols-3" data-picks></div>';
  }

  function filterPicks(picks, f) {
    const q = normText(f.q).trim();
    return picks.filter((p) => {
      if (f.channel && p.channel !== f.channel) return false;
      if (f.category && p.category !== f.category) return false;
      if (!q) return true;
      const hay = normText([p.game, p.selection, p.channel, p.reasoning, p.market, catLabel(p.category), p.line].join(' '));
      return hay.includes(q);
    });
  }

  function bindWeek(tab, panel) {
    const box = panel.querySelector('[data-filters]');
    const d = state.weekData[tab.id];
    if (!box || !d) return;
    const update = () => {
      const f = state.filters[tab.id];
      box.querySelectorAll('[data-f]').forEach((el) => { f[el.dataset.f] = el.value; });
      drawPicks(tab, panel, d);
    };
    box.addEventListener('input', update);
    box.addEventListener('change', update);
    drawPicks(tab, panel, d);
  }

  function drawPicks(tab, panel, d) {
    const picks = arr(d.picks).filter(isObj);
    const shown = filterPicks(picks, state.filters[tab.id]);
    const count = panel.querySelector('[data-count]');
    const list = panel.querySelector('[data-picks]');
    if (count) count.textContent = `Mostrando ${shown.length} de ${picks.length} picks`;
    if (list) list.innerHTML = shown.length ? shown.map((p) => pickCard(p, d)).join('') : empty('Ningún pick coincide con los filtros.');
  }

  function lineText(p) {
    if (p.line == null || p.line === '') return '';
    const n = toNum(p.line);
    if (n === null) return `Línea ${p.line}`;
    return `Línea ${p.market === 'spread' && n > 0 ? '+' : ''}${n}`;
  }

  function pickOdds(p) {
    const am = toNum(p.odds_american);
    const dec = toNum(p.odds_decimal);
    if (am === null && dec === null) return '<span class="muted small">sin momio en el video</span>';
    const main = am !== null ? fmtAmerican(am) : fmtDecimal(dec);
    const extra = am !== null && dec !== null ? ` <span class="muted small">(${esc(fmtDecimal(dec))} decimal)</span>` : '';
    return `<span class="muted small">Momio</span> <strong>${esc(main)}</strong>${extra}`;
  }

  function crossHtml(c) {
    if (!isObj(c)) return '';
    const stats = `hit ${fmtPct(c.hit_rate)}, n=${fmtNum(c.n)}`;
    if (c.tag === 'fuerte') return `<div class="cross cross-good">✓ tu fuerte <span class="muted">(${esc(stats)})</span></div>`;
    if (c.tag === 'debil') return `<div class="cross cross-bad">⚠ tu débil <span class="muted">(${esc(stats)})</span></div>`;
    return `<div class="cross muted">Tendencia neutral (${esc(stats)})</div>`;
  }

  function bookOdds(key, b) {
    const book = arr(obj(state.data.config).books).find((x) => x && x.key === key);
    const decimal = toNum(b.decimal);
    const american = toNum(b.american);
    if (book && book.odds_format === 'decimal' && decimal !== null) return fmtDecimal(decimal);
    if (american !== null) return fmtAmerican(american);
    return decimal !== null ? fmtDecimal(decimal) : NA;
  }

  function oddsCompareHtml(oc) {
    const books = obj(obj(oc).books);
    if (!isObj(oc) || !Object.keys(books).length) return '<div class="muted small">sin momios capturados</div>';
    const configured = arr(obj(state.data.config).books).map((b) => b && b.key).filter(Boolean);
    const keys = uniq(configured.concat(Object.keys(books)));
    const chips = keys.map((k) => {
      const b = books[k];
      if (!isObj(b)) return `<span class="chip chip-empty">${esc(bookName(k))}: sin momio</span>`;
      const best = k === oc.best_book;
      const title = `${bookName(k)}: ${fmtAmerican(b.american)} americano, ${fmtDecimal(b.decimal)} decimal`;
      return `<span class="chip${best ? ' chip-best' : ''}" title="${esc(title)}">${esc(bookName(k))} <b>${esc(bookOdds(k, b))}</b>` +
        `${best ? '<span class="chip-tag">mejor</span>' : ''}</span>`;
    }).join('');
    const diff = toNum(oc.diff_pct_vs_peor);
    const note = diff !== null
      ? `${bookName(oc.best_book)} paga ${fmtNum(diff, 1)}% más que la peor casa`
      : 'Solo una casa capturada';
    return `<div class="chips">${chips}</div><div class="muted small" style="margin-top:4px">${esc(note)}</div>`;
  }

  function videoUrlFor(p, d) {
    const direct = safeUrl(p.url) || safeUrl(p.video_url);
    if (direct) return direct;
    const sources = arr(d.sources).filter(isObj);
    if (p.video_id) {
      const s = sources.find((x) => x.video_id === p.video_id);
      return (s && safeUrl(s.url)) || `https://www.youtube.com/watch?v=${encodeURIComponent(p.video_id)}`;
    }
    const same = sources.filter((s) => s.channel === p.channel && safeUrl(s.url));
    return same.length === 1 ? same[0].url : null;
  }

  function timestampHtml(p, d) {
    if (!p.timestamp) return '';
    const secs = tsToSeconds(p.timestamp);
    const url = videoUrlFor(p, d);
    const href = url && secs !== null ? withTime(url, secs) : null;
    if (href) return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">▶ ${esc(p.timestamp)}</a>`;
    return `<span title="No se sabe de cuál video es este pick">${esc(p.timestamp)}</span>`;
  }

  function pickCard(p, d) {
    const res = RESULTS[p.result];
    const badges = [
      p.confidence ? badge(`Confianza ${p.confidence} (inferido)`, CONFIDENCE_TONES[p.confidence] || 'neutral', 'Confianza inferida del tono del video') : '',
      p.is_lock ? badge('LOCK', 'accent') : '',
      p.verified === false ? badge('No verificado', 'warn', 'Pick sin verificar contra el video') : '',
      res ? badge(res[0], res[1]) : '',
    ].join('');
    const meta = [MARKET_LABELS[p.market] || p.market, p.category ? catLabel(p.category) : '', lineText(p),
      toNum(p.units) !== null ? `${fmtNum(p.units, 2)} u` : ''].filter(Boolean).map(esc).join(' · ');
    const kickoff = p.kickoff ? fmtDate(p.kickoff) : '';
    return '<article class="card pick">' +
      `<div class="pick-top"><span class="pick-game">${esc(p.game || 'Partido sin dato')}</span><span>${esc(kickoff)}</span></div>` +
      `<div class="pick-sel">${esc(p.selection || NA)}</div>` +
      (meta ? `<div class="pick-meta">${meta}</div>` : '') +
      `<div class="pick-odds">${pickOdds(p)}</div>` +
      (badges ? `<div class="badges">${badges}</div>` : '') +
      crossHtml(p.cross) +
      `<div>${oddsCompareHtml(p.odds_compare)}</div>` +
      (p.reasoning ? `<p class="reason">${esc(p.reasoning)}</p>` : '') +
      `<div class="pick-foot"><span>${esc(p.channel || 'Canal sin dato')}</span>${timestampHtml(p, d)}</div>` +
      '</article>';
  }

  function insightsList(insights) {
    const items = arr(insights).map((x) => {
      if (typeof x === 'string') return x;
      if (!isObj(x)) return '';
      const text = x.text || x.insight || x.summary || '';
      return text && x.channel ? `${text} (${x.channel})` : text;
    }).filter((t) => t && String(t).trim());
    return items.length ? `<div class="card">${markList(items)}</div>` : empty('Sin insights todavía.');
  }

  function recordTable(rec, label) {
    const entries = Object.entries(obj(rec)).filter(([, v]) => isObj(v));
    if (!entries.length) return '';
    const rows = entries.sort((x, y) => x[0].localeCompare(y[0])).map(([ch, v]) => [
      esc(ch),
      numCell(`${esc(fmtNum(v.win || 0))}-${esc(fmtNum(v.loss || 0))}-${esc(fmtNum(v.push || 0))}`),
      numCell(`<span class="${toneClass(toNum(v.units))}">${esc(fmtUnits(v.units || 0))}</span>`),
    ]);
    return table(['Canal', th('W-L-P', 'r'), th('Unidades', 'r')], rows, label);
  }

  function recordSection(d) {
    const season = recordTable(obj(state.data.index).channel_record, 'Récord de la temporada');
    const week = isObj(d.record) ? recordTable(d.record, 'Récord de la semana') : '';
    return '<h3 class="sub-title">Temporada completa</h3>' +
      (season || '<p class="muted small">Sin picks calificados todavía.</p>') +
      (week ? `<h3 class="sub-title">Esta semana</h3>${week}` : '');
  }

  // =====================================================================
  // Carga de datos, pestañas y ruteo por hash
  // =====================================================================

  async function getJSON(path) {
    try {
      const res = await fetch(path, { cache: 'no-cache' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`No se pudo cargar ${path}:`, err);
      state.failed.push(path);
      return null;
    }
  }

  async function loadAll() {
    const keys = Object.keys(DATA_FILES);
    const values = await Promise.all(keys.map((k) => getJSON(DATA_FILES[k])));
    keys.forEach((k, i) => { state.data[k] = values[i]; });
  }

  function weekTabId(w, mainSeason) {
    const base = `w${pad2(Number(w.week) || 0)}`;
    return !mainSeason || w.season === mainSeason ? base : `${base}-${w.season}`;
  }

  function buildTabs() {
    const index = obj(state.data.index);
    const season = index.season || obj(state.data.config).season || 2026;
    const weeks = arr(index.weeks).filter(isObj)
      .sort((x, y) => (Number(x.season) - Number(y.season)) || (Number(x.week) - Number(y.week)));
    state.tabs = [
      { id: 'bankroll', label: `Bankroll ${season}`, render: renderBankroll },
      { id: 'tendencias', label: 'Mis tendencias', render: renderTendencias },
      { id: 'historial', label: 'Historial 24/25', render: renderHistorial },
    ];
    const seen = new Set(state.tabs.map((t) => t.id));
    weeks.forEach((w) => {
      const id = weekTabId(w, season);
      if (seen.has(id)) return;
      seen.add(id);
      const label = `Semana ${w.week}${w.season && w.season !== season ? ` (${w.season})` : ''}`;
      state.tabs.push({ id, label, week: w, render: renderWeek, bind: bindWeek, count: Number(w.n_picks) || 0 });
    });
    $('#tabs').innerHTML = state.tabs.map((t) =>
      `<a class="tab" id="tab-${t.id}" href="#${t.id}">${esc(t.label)}${t.count ? `<span class="tab-count">${t.count}</span>` : ''}</a>`).join('');
    $('#panels').innerHTML = state.tabs.map((t) =>
      `<section class="panel" id="panel-${t.id}" aria-labelledby="tab-${t.id}" hidden></section>`).join('');
  }

  function resolveHash() {
    let raw = '';
    try {
      raw = decodeURIComponent(window.location.hash.replace(/^#/, '')).trim().toLowerCase();
    } catch (err) {
      raw = '';
    }
    if (!raw) return null;
    const m = /^w(\d{1,2})$/.exec(raw);
    const id = m ? `w${pad2(Number(m[1]))}` : raw;
    return state.tabs.some((t) => t.id === id) ? id : null;
  }

  function defaultTabId() {
    const weeks = state.tabs.filter((t) => t.week);
    const last = weeks[weeks.length - 1];
    return last && Number(last.week.n_picks) > 0 ? last.id : 'bankroll';
  }

  function route(initial) {
    const id = resolveHash() || defaultTabId();
    if (window.location.hash !== `#${id}`) {
      try {
        window.history.replaceState(null, '', `#${id}`);
      } catch (err) {
        /* sin history API: seguimos sin tocar la URL */
      }
    }
    activate(id, initial);
  }

  function activate(id, initial) {
    const tab = state.tabs.find((t) => t.id === id);
    if (!tab) return;
    const changed = state.current !== id;
    state.current = id;
    state.tabs.forEach((t) => {
      const link = $(`#tab-${t.id}`);
      const panel = $(`#panel-${t.id}`);
      if (link) {
        if (t.id === id) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      }
      if (panel) panel.hidden = t.id !== id;
    });
    scrollTabIntoView(id);
    if (!initial && changed) window.scrollTo(0, 0);
    document.title = `${tab.label} | MazoPicks`;
    ensureRendered(tab);
  }

  function scrollTabIntoView(id) {
    const nav = $('#tabs');
    const link = $(`#tab-${id}`);
    if (!nav || !link) return;
    const nr = nav.getBoundingClientRect();
    const lr = link.getBoundingClientRect();
    if (lr.left < nr.left || lr.right > nr.right) nav.scrollLeft += lr.left - nr.left - 16;
  }

  function ensureRendered(tab) {
    if (state.rendered.has(tab.id)) return;
    state.rendered.add(tab.id);
    paint(tab);
  }

  async function paint(tab) {
    const panel = $(`#panel-${tab.id}`);
    if (!panel) return;
    destroyCharts(tab.id);
    if (tab.week && !state.weekData[tab.id]) panel.innerHTML = '<p class="loading">Cargando semana...</p>';
    const view = createView(tab.id);
    try {
      const html = await tab.render(tab, view);
      panel.innerHTML = html;
      view.mount(panel);
      if (tab.bind) tab.bind(tab, panel);
    } catch (err) {
      console.error(`Error al mostrar ${tab.id}`, err);
      panel.innerHTML = banner('bad', 'Error al mostrar esta sección', String((err && err.message) || err));
    }
  }

  function rerenderAll() {
    state.tabs.forEach((t) => destroyCharts(t.id));
    state.rendered.clear();
    const tab = state.tabs.find((t) => t.id === state.current);
    if (tab) ensureRendered(tab);
  }

  function initToggle() {
    const btn = $('#toggle-amounts');
    if (!btn) return;
    const sync = () => {
      btn.textContent = state.hide ? 'Mostrar montos' : 'Ocultar montos';
      btn.setAttribute('aria-pressed', String(state.hide));
      document.body.classList.toggle('amounts-hidden', state.hide);
    };
    sync();
    btn.addEventListener('click', () => {
      state.hide = !state.hide;
      writeHide(state.hide);
      sync();
      rerenderAll();
    });
  }

  function renderAlerts() {
    const box = $('#alerts');
    if (!box) return;
    const parts = [];
    if (state.failed.length) {
      parts.push(banner('bad', 'Faltan datos', `No se pudieron cargar: ${state.failed.join(', ')}. El resto del sitio funciona con lo disponible.`));
    }
    if (obj(state.data.index).show_amounts === false) {
      parts.push(banner('info', 'Montos ocultos en la publicación', 'El build ocultó los montos MXN (show_amounts = false). Se muestran ROI y porcentajes.'));
    }
    box.innerHTML = parts.join('');
  }

  function renderFooter() {
    const el = $('#generated');
    if (el) el.textContent = `Datos generados: ${fmtDate(obj(state.data.index).generated_at)}`;
  }

  async function init() {
    initToggle();
    initChartLib();
    await loadAll();
    renderAlerts();
    renderFooter();
    buildTabs();
    window.addEventListener('hashchange', () => route(false));
    route(true);
  }

  function start() {
    init().catch((err) => {
      console.error('Error al iniciar MazoPicks', err);
      const panels = $('#panels');
      if (panels) panels.innerHTML = banner('bad', 'No se pudo iniciar el sitio', String((err && err.message) || err));
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
