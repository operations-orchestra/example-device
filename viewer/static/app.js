'use strict';
/* Operations Record browser.
   Every number shown comes from the local service, which calls the Record's own read
   methods with the time control's "as of" value. This file only draws; it never filters
   by time itself. Zooming a chart changes what is drawn, not what was fetched. */

const S = { meta: null, asOf: 0, prev: null, pin: null, prod: false, planted: false, elements: [], plantedData: null };
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (t) => (t == null ? '–' : new Date(t * 1000).toISOString().slice(0, 19).replace('T', ' '));
const fmtShort = (t) => fmt(t).slice(5, 16);
const num = (v) => (v == null ? '–' : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? (+v.toFixed(3)).toString() : (+v.toFixed(4)).toString());
function parseT(s) {
  const m = Date.parse(s.trim().replace(' ', 'T').replace(/Z$/, '') + 'Z');
  return Number.isNaN(m) ? null : Math.floor(m / 1000);
}
function dur(s) {
  if (s == null) return '–';
  const a = Math.abs(s);
  if (a < 60) return `${s} s`;
  if (a < 3600) return `${Math.round(s / 60)} min`;
  if (a < 86400) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} d`;
}
function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* storage may be unavailable; the page works without it */ }
  return null;
}
async function api(route, params = {}, withAsOf = true) {
  const q = new URLSearchParams(withAsOf ? { as_of: S.asOf, ...params } : params);
  const r = await fetch(`/api/${route}?${q}`);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || `request failed (${r.status})`);
  return j;
}

const EXPERT = '<span class="badge expert" data-tip="Expert-filled: in a real Record this exists only where experts have reviewed the incident. Here the generator wrote it for every incident.">expert-filled</span>';
const DEMO = '<span class="badge demo" data-tip="Demo only: exists because the data is synthetic and we hold the answers. No counterpart in production.">demo only</span>';
const demoBand = (text) => `<div class="demo-band">${DEMO} ${text}</div>`;
const showDemo = () => !S.prod && S.meta.has_planted;
const showPlanted = () => showDemo() && S.planted;

function describe(e) {
  const p = e.payload || {};
  if (p.text) return `${p.author_role || '?'}: ${p.text}`;
  if (e.type === 'lv_voltage' || e.type === 'temperature') return `mean ${p.mean} ${p.unit}, min ${p.min}, max ${p.max}, slope ${p.slope_per_h}/h`;
  if (e.type === 'downtime') return `${Math.floor(p.duration_s / 60)} min, ${p.lost_lumi_pb} /pb lost, ${p.category}: ${p.details}`;
  return Object.entries(p).map(([k, v]) => `${k}=${Array.isArray(v) ? JSON.stringify(v) : v}`).join(', ');
}
const unknown = '<span class="unknown">not known at this time</span>';
const entryLink = (id) => `<a href="#/entry/${id}">${id}</a>`;
const elLink = (name) => `<a href="#/timeline/${encodeURIComponent(name)}">${esc(name)}</a>`;
const incLink = (id, title) => `<a href="#/incident/${id}">#${id}${title ? ' ' + esc(title) : ''}</a>`;
const asofBtn = (t, label) => `<button data-asof="${t}" title="Set the time control to ${fmt(t)}">${label}</button>`;

function entryRows(entries, extra) {
  return entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}">
    ${extra ? extra(e) : ''}<td class="t">${fmt(e.t_start)}</td><td class="t">${fmt(e.known_at)}</td>
    <td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td>
    <td class="what">${esc(describe(e))}</td></tr>`).join('');
}
const ENTRY_HEAD = '<th>Happened</th><th>Known to the Record</th><th class="num">id</th><th>Class</th><th>Source / type</th><th>Element</th><th>What</th>';

/* ------------------------------------------------------------------ time control */
function setAsOf(t, keepPrev) {
  t = Math.max(S.meta.t0, Math.min(S.meta.latest_known_at, Math.round(t)));
  if (t === S.asOf) return;
  if (!keepPrev) S.prev = S.asOf;
  S.asOf = t;
  syncHash();
  render();
}
function syncHash() {
  const path = location.hash.split('?')[0] || '#/home';
  history.replaceState(null, '', `${path}?t=${S.asOf}`);
}
async function updateClock() {
  $('#clock-text').value = fmt(S.asOf);
  const sl = $('#clock-slider');
  sl.min = S.meta.t0; sl.max = S.meta.latest_known_at; sl.value = S.asOf;
  $('#clock-pin').textContent = S.pin == null ? 'Pin for comparison' : `Unpin (${fmtShort(S.pin)})`;
  const base = S.pin ?? S.prev;
  const box = $('#diff');
  if (base == null || base === S.asOf) { box.hidden = true; return; }
  box.hidden = false;
  try {
    const d = await api('diff', { since: base });
    const dir = base < S.asOf ? 'learned' : 'did not yet know';
    $('#diff-summary').textContent = `Between ${fmt(d.from)} and ${fmt(d.to)} the Record ${dir}: ` +
      `${d.n_entries} entries, ${d.n_links} links, ${d.incident_changes.length} incident changes`;
    $('#diff-body').innerHTML =
      (d.incident_changes.length ? '<ul>' + d.incident_changes.map((c) => `<li>${fmt(c.t)} · ${incLink(c.incident_id, c.title)}: ${esc(c.what)}</li>`).join('') + '</ul>' : '') +
      (d.entries.length ? `<div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows(d.entries)}</table></div>` +
        (d.n_entries > d.entries.length ? `<p class="small muted">First ${d.entries.length} of ${d.n_entries} entries.</p>` : '') : '');
  } catch (e) { $('#diff-summary').textContent = e.message; }
}
function wireClock() {
  $('#clock-text').addEventListener('change', (ev) => {
    const t = parseT(ev.target.value);
    if (t == null) { ev.target.value = fmt(S.asOf); return; }
    setAsOf(t);
  });
  $('#clock-slider').addEventListener('change', (ev) => setAsOf(+ev.target.value));
  $('#clock-slider').addEventListener('input', (ev) => { $('#clock-text').value = fmt(+ev.target.value); });
  const step = async (direction) => {
    const r = await api('next_known', { t: S.asOf, direction }, false);
    if (r.t != null) setAsOf(r.t);
  };
  $('#clock-prev').addEventListener('click', () => step('previous'));
  $('#clock-next').addEventListener('click', () => step('next'));
  $('#clock-cal-end').addEventListener('click', () => setAsOf(S.meta.t1));
  $('#clock-end').addEventListener('click', () => setAsOf(S.meta.latest_known_at));
  $('#clock-pin').addEventListener('click', () => { S.pin = S.pin == null ? S.asOf : null; updateClock(); });
}

/* ------------------------------------------------------------------------ charts */
const STEPS = [60, 300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400, 2 * 86400, 7 * 86400, 14 * 86400];
function ticks(t0, t1, max) {
  const step = STEPS.find((s) => (t1 - t0) / s <= max) || 28 * 86400;
  const out = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) out.push(t);
  return { step, out };
}
function tickLabel(t, step) {
  const iso = new Date(t * 1000).toISOString();
  return step >= 86400 || iso.slice(11, 16) === '00:00' ? iso.slice(5, 10) : iso.slice(11, 16);
}
function niceTicks(d0, d1) {
  const raw = (d1 - d0) / 3, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
  const step = (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.ceil(d0 / step - 1e-9) * step; v <= d1 + 1e-9; v += step) out.push(+v.toPrecision(10));
  return out;
}
function yDomain(panel, t0, t1, typical) {
  const vs = [];
  let lo = Infinity, hi = -Infinity;
  const single = panel.series.length === 1;
  for (const s of panel.series) for (const p of s.points) {
    if (p.t1 < t0 || p.t0 > t1) continue;
    vs.push(p.v);
    lo = Math.min(lo, single && p.lo != null ? p.lo : p.v);
    hi = Math.max(hi, single && p.hi != null ? p.hi : p.v);
  }
  if (!vs.length) return [0, 1];
  if (typical) {
    vs.sort((a, b) => a - b);
    lo = vs[Math.floor(vs.length * 0.05)]; hi = vs[Math.min(vs.length - 1, Math.ceil(vs.length * 0.95))];
  } else if (panel.unit === 'fraction') { lo = 0; hi = Math.max(hi, 1); }
  if (hi - lo < 1e-9) { const pad = Math.abs(hi) * 0.01 || 0.01; lo -= pad; hi += pad; }
  const pad = (hi - lo) * 0.12;
  return [lo - pad, hi + pad];
}
/* One time axis shared by reading panels (optional) and rows of recorded events. */
function buildChart(cfg) {
  const L = 118, R = 26, W = Math.max(520, cfg.width), PH = 92, RH = 22;
  const X = (t) => L + ((t - cfg.t0) / (cfg.t1 - cfg.t0)) * (W - L - R);
  const cx = (t) => Math.max(L, Math.min(W - R, X(t)));
  const id = 'c' + Math.random().toString(36).slice(2, 8);
  let y = 20, body = '';
  const geom = [];
  for (const p of cfg.panels || []) {
    const top = y + 18, bot = top + PH;
    const [d0, d1] = yDomain(p, cfg.t0, cfg.t1, cfg.typical);
    const Y = (v) => bot - ((v - d0) / (d1 - d0)) * PH;
    geom.push({ panel: p, top, bot });
    body += `<text class="title" x="${L}" y="${y + 10}">${esc(p.label)} (${esc(p.unit)})</text>`;
    for (const v of niceTicks(d0, d1)) {
      body += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${num(v)}</text>`;
    }
    let marks = '';
    p.series.forEach((s, i) => {
      const cls = `c${i + 1}`;
      const pts = s.points.filter((q) => q.t1 >= cfg.t0 && q.t0 <= cfg.t1);
      if (p.per_run) {
        for (const q of pts) marks += `<line class="line ${cls}" x1="${X(q.t0)}" x2="${X(q.t1)}" y1="${Y(q.v)}" y2="${Y(q.v)}"/>`;
        return;
      }
      let d = '', prev = null, up = '', down = [];
      for (const q of pts) {
        const xm = X((q.t0 + q.t1) / 2);
        const gap = prev && q.t0 - prev.t1 > 1.5 * (q.t1 - q.t0);
        d += `${prev && !gap ? 'L' : 'M'}${xm.toFixed(1)},${Y(q.v).toFixed(1)}`;
        if (p.series.length === 1 && q.lo != null) { up += `${up ? 'L' : 'M'}${xm.toFixed(1)},${Y(q.hi).toFixed(1)}`; down.push(`L${xm.toFixed(1)},${Y(q.lo).toFixed(1)}`); }
        prev = q;
      }
      if (up) marks += `<path class="band ${cls}" d="${up}${down.reverse().join('')}Z"/>`;
      marks += `<path class="line ${cls}" d="${d}"/>`;
    });
    body += `<g clip-path="url(#${id})">${marks}</g><line class="axis" x1="${L}" x2="${W - R}" y1="${bot}" y2="${bot}"/>`;
    y = bot + 14;
  }
  const rowsTop = y + 6;
  for (const row of cfg.rows || []) {
    const mid = y + RH / 2 + 6;
    body += `<text x="${L - 8}" y="${mid + 4}" text-anchor="end">${esc(row.label)}</text><line class="grid" x1="${L}" x2="${W - R}" y1="${mid}" y2="${mid}"/>`;
    for (const it of row.items) {
      const t1 = it.t1 === undefined ? undefined : (it.t1 ?? cfg.t1);
      if ((t1 ?? it.t0) < cfg.t0 || it.t0 > cfg.t1) continue;
      const attrs = `class="hit ${it.cls}" data-tip="${esc(it.tip || '')}"${it.go ? ` data-go="${it.go}"` : ''}`;
      const x = X(it.t0);
      if (t1 !== undefined) body += `<rect ${attrs} x="${cx(it.t0)}" y="${mid - 6}" width="${Math.max(2, cx(t1) - cx(it.t0))}" height="12" rx="2"/>`;
      else if (it.shape === 'tick') body += `<line ${attrs} x1="${x}" x2="${x}" y1="${mid - 7}" y2="${mid + 7}"/>`;
      else if (it.shape === 'tri') body += `<path ${attrs} d="M${x - 5},${mid - 5}L${x + 5},${mid - 5}L${x},${mid + 5}Z"/>`;
      else body += `<path ${attrs} d="M${x},${mid - 6}L${x + 6},${mid}L${x},${mid + 6}L${x - 6},${mid}Z"/>`;
    }
    y += RH;
  }
  const bottom = y + 10;
  const tk = ticks(cfg.t0, cfg.t1, Math.max(4, Math.floor((W - L - R) / 90)));
  let frame = '';
  for (const t of tk.out) frame += `<line class="grid" x1="${X(t)}" x2="${X(t)}" y1="20" y2="${bottom}"/><text x="${X(t)}" y="${bottom + 14}" text-anchor="middle">${tickLabel(t, tk.step)}</text>`;
  let lines = '';
  for (const v of cfg.vlines || []) {
    if (v.t < cfg.t0 || v.t > cfg.t1) continue;
    lines += `<line class="${v.cls}" x1="${X(v.t)}" x2="${X(v.t)}" y1="20" y2="${bottom}"/>`;
    if (v.label) lines += `<text class="hit" x="${X(v.t)}" y="13" text-anchor="middle" data-tip="${esc(v.tip || '')}"${v.go ? ` data-go="${v.go}"` : ''}>${esc(v.label)}</text>`;
  }
  const H = bottom + 34;
  const svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(cfg.aria || 'timeline')}">
    <defs><clipPath id="${id}"><rect x="${L}" y="20" width="${W - L - R}" height="${bottom - 20}"/></clipPath></defs>
    ${frame}${body}${lines}<line class="cross" id="${id}x" y1="20" y2="${bottom}" visibility="hidden"/><rect class="brush" id="${id}b" y="20" height="${bottom - 20}" visibility="hidden"/>
    <line class="axis" x1="${L}" x2="${W - R}" y1="${bottom}" y2="${bottom}"/>
    <text x="${W - R}" y="${bottom + 28}" text-anchor="end">UTC, ${fmt(cfg.t0)} to ${fmt(cfg.t1)}</text></svg>`;
  return { svg, id, L, R, W, geom, rowsTop, bottom, inv: (px) => cfg.t0 + ((px - L) / (W - L - R)) * (cfg.t1 - cfg.t0) };
}
/* drag to zoom, double-click to reset, crosshair with values */
function wireChart(host, chart, cfg, on) {
  const svg = host.querySelector('svg');
  const px = (ev) => (ev.clientX - svg.getBoundingClientRect().left) * (chart.W / svg.getBoundingClientRect().width);
  const cross = svg.querySelector(`#${chart.id}x`), brush = svg.querySelector(`#${chart.id}b`);
  let start = null;
  svg.addEventListener('mousedown', (ev) => { if (!ev.target.closest('.hit') && on.zoom) { start = px(ev); ev.preventDefault(); } });
  svg.addEventListener('mousemove', (ev) => {
    const x = px(ev);
    if (x < chart.L || x > chart.W - chart.R) { cross.setAttribute('visibility', 'hidden'); return; }
    cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
    if (start != null) {
      brush.setAttribute('x', Math.min(start, x)); brush.setAttribute('width', Math.abs(x - start)); brush.setAttribute('visibility', 'visible');
    }
    if (ev.target.closest('.hit')) return;
    const t = chart.inv(x);
    let text = fmt(Math.round(t));
    for (const g of chart.geom) for (const s of g.panel.series) {
      const p = s.points.find((q) => q.t0 <= t && t <= q.t1);
      if (p) text += `\n${g.panel.label}${g.panel.series.length > 1 ? ' ' + s.box : ''}: ${num(p.v)}`;
    }
    showTip(text, ev);
  });
  svg.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); start = null; brush.setAttribute('visibility', 'hidden'); });
  svg.addEventListener('mouseup', (ev) => {
    if (start == null) return;
    const x = px(ev), a = chart.inv(Math.min(start, x)), b = chart.inv(Math.max(start, x));
    const moved = Math.abs(x - start);
    start = null; brush.setAttribute('visibility', 'hidden');
    if (moved > 6 && b - a > 120) on.zoom(Math.round(a), Math.round(b));
    else if (on.click && !ev.target.closest('.hit')) on.click(Math.round(chart.inv(x)));
  });
  if (on.reset) svg.addEventListener('dblclick', on.reset);
}
function showTip(text, ev) {
  const tip = $('#tip');
  tip.textContent = text; tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(window.innerWidth - w - 8, ev.clientX + 14) + 'px';
  tip.style.top = (ev.clientY + 16 + h > window.innerHeight ? ev.clientY - h - 10 : ev.clientY + 16) + 'px';
}
const hideTip = () => { $('#tip').hidden = true; };

/* ------------------------------------------------------------------------- pages */
const PAGES = {};
const NAV = [
  ['Record', [['home', 'Home'], ['record', 'Entries'], ['incidents', 'Incidents'], ['timeline', 'Timeline'], ['precedents', 'Precedents'], ['api', 'Read API']]],
  ['Demo only', [['device', 'Device and faults'], ['planted', 'Planted answers']]],
];
function drawNav(current) {
  $('#nav').innerHTML = NAV.filter(([g]) => g === 'Record' || showDemo()).map(([g, items]) =>
    `<div class="${g === 'Demo only' ? 'demo-group' : ''}"><div class="group">${g}</div>${items.map(([k, label]) =>
      `<a href="#/${k}" class="${current === k || (k === 'incidents' && current === 'incident') || (k === 'record' && current === 'entry') ? 'on' : ''}">${label}</a>`).join('')}</div>`).join('');
}

PAGES.home = async () => {
  const o = await api('overview');
  const m = S.meta;
  const rows = [
    { label: 'Stable beams', items: o.beam.filter((b) => b.mode === 'STABLE BEAMS').map((b) => ({ t0: b.t0, t1: b.t1, cls: 'beam', tip: `Stable beams ${fmt(b.t0)} to ${fmt(b.t1)}` })) },
    { label: 'Technical stop', items: o.beam.filter((b) => b.mode === 'TECHNICAL STOP').map((b) => ({ t0: b.t0, t1: b.t1, cls: 'beam', tip: `Technical stop ${fmt(b.t0)} to ${fmt(b.t1)}` })) },
    { label: 'Downtime', items: o.downtime.map((e) => ({ t0: e.t_start, t1: e.t_end, cls: 'down', tip: describe(e), go: `#/entry/${e.id}` })) },
    { label: 'Incidents', items: o.incidents.map((i) => ({ t0: i.t_start, shape: 'diamond', cls: 'mk', tip: `#${i.id} ${i.title} (${i.status})`, go: `#/incident/${i.id}` })) },
  ];
  const byClass = { MS: 'Machine state', QA: 'Quality assurance', HI: 'Human interpretation' };
  const html = `<h1>What is loaded</h1>
  <p class="muted">${esc(m.banner)}</p>
  <div class="cols"><div class="card"><dl class="facts">
    <dt>Record file</dt><dd class="mono">${esc(m.path)} (${m.size_mb} MB, opened read-only)</dd>
    <dt>Built by</dt><dd>preset <b>${esc(m.preset)}</b>, seed ${esc(m.seed)}, schema ${esc(m.schema_version)}</dd>
    <dt>Calendar</dt><dd>${fmt(m.t0)} to ${fmt(m.t1)} UTC</dd>
    <dt>Last thing learned</dt><dd>${fmt(m.latest_known_at)}</dd>
    <dt>Known at this time</dt><dd><b>${o.n_entries}</b> of ${o.tables.entry} entries, <b>${o.incidents.length}</b> of ${o.tables.incident} incidents</dd>
    <dt>Elements</dt><dd>${Object.entries(o.elements_by_kind).map(([k, n]) => `${n} ${k.replace('_', ' ')}`).join(', ')}</dd>
  </dl></div>
  <div class="card"><b>How to read this GUI</b>
    <p>Everything is shown as the Record stood at the time in the bar above. Move the time and entries, labels and links appear in the order the Record learned them.</p>
    <p>Three marks tell you what would exist with real records:</p>
    <p>no mark: production-like, uses only what is in the Record.<br>${EXPERT} present in production only where experts reviewed an incident.<br>${DEMO} exists only because the data is synthetic. The "Production view" switch hides all of it.</p>
  </div></div>
  <h2>Calendar</h2><p class="muted small">Click anywhere on the strip to set the time control to that moment. The blue line is the time control.</p>
  <div id="cal"></div>
  <h2>Components</h2>
  <div class="flow">
    <div class="box off"><b>Feed</b>adapters, anonymizer, summarizer, sparsifier<br><span class="small">interfaces only, not built</span></div>
    ${S.prod ? '' : `<a class="box demo" href="#/device"><b>Example device</b>synthetic generator standing in for the feed<br>${DEMO}</a>`}
    <span class="arrow">&#8594;</span>
    <a class="box" href="#/record"><b>The Record</b>entries, links, incidents<br><span class="small">Entries · Incidents · Timeline</span></a>
    <span class="arrow">&#8594;</span>
    <a class="box" href="#/api"><b>Read API</b>as-of reads, run by hand<br><span class="small">Read API · Precedents</span></a>
    <span class="arrow">&#8594;</span>
    <div class="box off"><b>Query tools and agent</b><span class="small">designed, not built</span></div>
  </div>
  <h2>Entries known at this time, by class and type</h2>
  <div class="tablewrap"><table><tr><th>Class</th><th>Source</th><th>Type</th><th>Kind</th><th class="num">Entries</th></tr>
  ${o.entries_by_type.map(([c, s, t, k, n]) => `<tr class="click" data-go="#/record" data-filter='${JSON.stringify({ cls: c, source: s, type: t })}'><td>${byClass[c]}</td><td>${esc(s)}</td><td>${esc(t)}</td><td>${k}</td><td class="num">${n}</td></tr>`).join('')}
  </table></div>`;
  return { html, mount() {
    const host = $('#cal');
    const cfg = { t0: m.t0, t1: m.t1, width: host.clientWidth, rows, vlines: [{ t: S.asOf, cls: 'asof' }], aria: 'calendar of fills, downtime and incidents' };
    const chart = buildChart(cfg);
    host.innerHTML = chart.svg;
    wireChart(host, chart, cfg, { click: (t) => setAsOf(t) });
  } };
};

const RF = { cls: '', source: '', type: '', kind: '', element: '', below: false, q: '', order: 'oldest', offset: 0 };
const TABLES = [
  ['element', 'Parts of the device, in a hierarchy'], ['element_relation', 'Service links: which supply powers a box, which FED reads it'],
  ['entry', 'Every reading summary, event, note and flag, in one common envelope'], ['link', 'Connections between entries: direct (same place and time) or indirect (expert reasoning)'],
  ['incident', 'Problems people grouped entries into, with recovery, cause and certification kept apart'], ['incident_entry', 'Which entries belong to which incident, and in what role'],
  ['query_log', 'Every read made by the agent tools (empty until they exist)'], ['meta', 'What built this Record']];
PAGES.record = async () => {
  const o = await api('overview');
  const params = { limit: 100, offset: RF.offset, order: RF.order };
  if (RF.cls) params.class = RF.cls; if (RF.source) params.source = RF.source; if (RF.type) params.type = RF.type;
  if (RF.kind) params.kind = RF.kind; if (RF.q) params.q = RF.q;
  if (RF.element) { params.element = RF.element; if (RF.below) params.below = 1; }
  const d = await api('entries', params);
  const uniq = (i) => [...new Set(o.entries_by_type.map((r) => r[i]))].sort();
  const sel = (key, label, values) => `<label>${label} <select data-rf="${key}"><option value="">all</option>${values.map((v) => `<option${RF[key] === v ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  const html = `<h1>Entries</h1>
  <p class="muted">Every row of the Record, as known at the time control. Click a row for the full entry.</p>
  <details><summary>The eight tables of the Record</summary><div class="tablewrap"><table><tr><th>Table</th><th class="num">Rows in total</th><th>Holds</th></tr>
  ${TABLES.map(([t, what]) => `<tr><td class="mono">${t}</td><td class="num">${t === 'meta' ? '' : o.tables[t]}</td><td>${what}</td></tr>`).join('')}</table></div></details>
  <div class="filters">
    ${sel('cls', 'Class', uniq(0))}${sel('source', 'Source', uniq(1))}${sel('type', 'Type', uniq(2))}${sel('kind', 'Kind', uniq(3))}
    ${sel('element', 'Element', S.elements.map((e) => e.name))}
    <label><input type="checkbox" data-rf="below"${RF.below ? ' checked' : ''}> and everything below it</label>
    <label>Text <input type="text" data-rf="q" value="${esc(RF.q)}" placeholder="search the payload"></label>
    <label>Order <select data-rf="order"><option value="oldest"${RF.order === 'oldest' ? ' selected' : ''}>oldest first</option><option value="newest"${RF.order === 'newest' ? ' selected' : ''}>newest first</option></select></label>
    <button data-rf-clear>Clear</button>
  </div>
  <div class="pager"><b>${d.total}</b> entries match. Showing ${d.total ? RF.offset + 1 : 0} to ${RF.offset + d.entries.length}.
    <button data-rf-page="-100"${RF.offset ? '' : ' disabled'}>&#9664; previous</button><button data-rf-page="100"${RF.offset + 100 < d.total ? '' : ' disabled'}>next &#9654;</button></div>
  <div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows(d.entries)}</table></div>`;
  return { html, mount() {
    document.querySelectorAll('[data-rf]').forEach((el) => el.addEventListener('change', () => {
      RF[el.dataset.rf] = el.type === 'checkbox' ? el.checked : el.value; RF.offset = 0; render();
    }));
    $('[data-rf-clear]').addEventListener('click', () => { Object.assign(RF, { cls: '', source: '', type: '', kind: '', element: '', below: false, q: '', offset: 0 }); render(); });
    document.querySelectorAll('[data-rf-page]').forEach((b) => b.addEventListener('click', () => { RF.offset = Math.max(0, RF.offset + (+b.dataset.rfPage)); render(); }));
  } };
};

PAGES.entry = async (parts) => {
  const d = await api('entry', { id: parts[1] });
  const e = d.entry;
  const html = `<h1>Entry ${e.id}</h1><p class="muted">${esc(describe(e))}</p>
  <div class="cols"><div class="card"><dl class="facts">
    <dt>Class</dt><dd>${e.record_class}</dd><dt>Source / type</dt><dd>${esc(e.source)} / ${esc(e.type)}</dd><dt>Kind</dt><dd>${e.kind}</dd>
    <dt>Element</dt><dd>${d.element_path.map(elLink).join(' &lsaquo; ')}</dd>
    <dt>Happened</dt><dd>${fmt(e.t_start)}${e.t_end ? ' to ' + fmt(e.t_end) : ''}</dd>
    <dt>Known to the Record</dt><dd>${fmt(e.known_at)} <span class="muted">(${dur(e.known_at - e.t_start)} after it started)</span> ${asofBtn(e.known_at, 'go to this moment')}</dd>
    <dt>Producer</dt><dd class="mono">${esc(e.producer)} ${esc(e.producer_version)}</dd>
    <dt>Source pointer</dt><dd class="mono">${esc(e.raw_ref)}</dd>
    <dt>Review status</dt><dd>${e.review_status}</dd>
    <dt>Corrects</dt><dd>${e.supersedes ? entryLink(e.supersedes) : 'nothing'}</dd>
    <dt>Corrected by</dt><dd>${d.superseded_by ? entryLink(d.superseded_by) : 'nothing'}</dd>
  </dl></div><div class="card"><b>Payload</b><pre>${esc(JSON.stringify(e.payload, null, 2))}</pre></div></div>
  <h2>Incidents this entry is attached to ${EXPERT}</h2>
  ${d.incidents.length ? '<ul>' + d.incidents.map((i) => `<li>${incLink(i.id, i.title)} as <b>${esc(i.role)}</b></li>`).join('') + '</ul>' : '<p class="muted">None known at this time.</p>'}
  <h2>Links</h2>
  ${d.links.length ? `<div class="tablewrap"><table><tr><th>Link</th><th>Other entry</th><th>What it is</th><th>Reason given</th><th>Known</th></tr>${d.links.map((l) =>
    `<tr><td>${l.link_type} ${l.link_type === 'indirect' ? EXPERT : ''}<br>${l.direction === 'out' ? 'this ' + esc(l.relation) + ' &#8594;' : '&#8592; ' + esc(l.relation) + ' this'}</td>
     <td>${entryLink(l.other.id)}</td><td class="what">${esc(describe(l.other))}</td><td class="what">${esc(l.rationale)}</td><td class="t">${fmt(l.known_at)}</td></tr>`).join('')}</table></div>` : '<p class="muted">None known at this time.</p>'}`;
  return { html };
};

const statusCell = (s) => `<span class="status">${s}</span>`;
PAGES.incidents = async () => {
  const d = await api('incidents');
  const html = `<h1>Incidents</h1>
  <p class="muted">Problems as the Record knew them at the time control. Grouping entries into an incident, and the three labels, are ${EXPERT}.</p>
  <div class="tablewrap"><table><tr><th>#</th><th>Started</th><th>Status</th><th>Element</th><th>Title</th><th>Recovery action</th><th>Confirmed cause</th><th>Certification</th></tr>
  ${d.incidents.map((i) => `<tr class="click" data-go="#/incident/${i.id}"><td class="num">${i.id}</td><td class="t">${fmt(i.t_start)}</td><td>${statusCell(i.status)}</td><td>${esc(i.element)}</td><td>${esc(i.title)}</td>
    <td class="what">${i.recovery_action ? esc(i.recovery_action) : unknown}</td><td class="what">${i.confirmed_cause ? esc(i.confirmed_cause) : unknown}</td><td>${i.certification ? esc(i.certification) : unknown}</td></tr>`).join('')}
  </table></div>${d.incidents.length ? '' : '<p class="muted">No incident is known to the Record at this time.</p>'}`;
  return { html };
};

const ROLE_CLASS = { symptom: 'c1', downtime: 'c2', action: 'c3', certification: 'c4', cause: 'c5', closing_note: 'c5', evidence: 'c7' };
const ROLE_LABEL = { symptom: 'symptom', downtime: 'downtime', action: 'action taken', certification: 'certification', cause: 'cause or closing note', evidence: 'evidence linked by an expert' };
function knowledgeChart(inc, entries, width) {
  // Time is drawn relative to the start of the incident on a compressed scale, so minutes
  // and weeks fit on one axis: equal distance means ten times longer.
  const f = (dt) => Math.sign(dt) * Math.log10(1 + Math.abs(dt) / 60);
  const L = 118, R = 20, W = Math.max(520, width), yTop = 56, yBot = 170, H = 232;
  const all = entries.flatMap((e) => [e.t_start - inc.t_start, e.known_at - inc.t_start]).concat([S.asOf - inc.t_start, 0]);
  const lo = f(Math.min(...all)) - 0.2, hi = f(Math.max(...all)) + 0.2;
  const X = (dt) => L + ((f(dt) - lo) / (hi - lo)) * (W - L - R);
  let s = `<text x="${L - 8}" y="${yTop + 4}" text-anchor="end">Happened</text><text x="${L - 8}" y="${yBot + 4}" text-anchor="end">Known</text>
    <line class="axis" x1="${L}" x2="${W - R}" y1="${yTop}" y2="${yTop}"/><line class="axis" x1="${L}" x2="${W - R}" y1="${yBot}" y2="${yBot}"/>`;
  const marks = [[-7 * 86400, '1 wk before'], [-86400, '1 d before'], [-6 * 3600, '6 h before'], [-3600, '1 h before'], [-600, '10 min before'], [0, 'start'],
    [600, '+10 min'], [3600, '+1 h'], [6 * 3600, '+6 h'], [86400, '+1 d'], [7 * 86400, '+1 wk'], [14 * 86400, '+2 wk'], [28 * 86400, '+4 wk']];
  for (const [dt, label] of marks) {
    if (f(dt) < lo || f(dt) > hi) continue;
    s += `<line class="grid" x1="${X(dt)}" x2="${X(dt)}" y1="${yTop - 14}" y2="${yBot + 14}"/><text x="${X(dt)}" y="${yBot + 30}" text-anchor="middle">${label}</text>`;
  }
  for (const e of entries) {
    const cls = ROLE_CLASS[e.role] || 'c1', a = X(e.t_start - inc.t_start), b = X(e.known_at - inc.t_start);
    const tip = `${e.role}: ${describe(e)}\nhappened ${fmt(e.t_start)}\nknown ${fmt(e.known_at)} (${dur(e.known_at - e.t_start)} later)`;
    s += `<g class="hit ${cls}" data-go="#/entry/${e.id}" data-tip="${esc(tip)}"><line x1="${a}" y1="${yTop}" x2="${b}" y2="${yBot}" stroke-width="2" opacity=".75"/>
      <circle cx="${a}" cy="${yTop}" r="5" stroke="var(--surface)" stroke-width="2"/><circle cx="${b}" cy="${yBot}" r="5" stroke="var(--surface)" stroke-width="2"/></g>`;
  }
  s += `<line class="asof" x1="${X(S.asOf - inc.t_start)}" x2="${X(S.asOf - inc.t_start)}" y1="${yTop - 20}" y2="${yBot + 14}"/><text x="${X(S.asOf - inc.t_start)}" y="${yTop - 26}" text-anchor="end">time control</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="when each entry happened and when it became known">${s}</svg>`;
}
let playTimer = null;
PAGES.incident = async (parts) => {
  const d = await api('incident', { id: parts[1] });
  const i = d.incident;
  const roles = [...new Set(d.entries.map((e) => (e.role === 'closing_note' ? 'cause' : e.role)))];
  const html = `<h1>Incident #${i.id}: ${esc(i.title)}</h1>
  <p class="muted">As the Record knew it at ${fmt(S.asOf)}. Grouping and labels are ${EXPERT}.</p>
  <div class="card"><dl class="facts">
    <dt>Status</dt><dd>${statusCell(i.status)}</dd><dt>Element</dt><dd>${elLink(i.element)}</dd>
    <dt>Started</dt><dd>${fmt(i.t_start)} ${asofBtn(i.t_start + 300, 'go to 5 min after the start')}</dd>
    <dt>Ended</dt><dd>${i.t_end ? fmt(i.t_end) + ` <span class="muted">(${dur(i.t_end - i.t_start)})</span>` : unknown}</dd>
    <dt>Incident opened</dt><dd>${fmt(i.known_at)}</dd>
    <dt>Recovery action</dt><dd>${i.recovery_action ? esc(i.recovery_action) : unknown}</dd>
    <dt>Confirmed cause</dt><dd>${i.confirmed_cause ? esc(i.confirmed_cause) : unknown}</dd>
    <dt>Certification</dt><dd>${i.certification ? esc(i.certification) : unknown}</dd>
  </dl></div>
  <div class="filters"><button id="play-prev">&#9664; previous thing learned</button><button id="play-next">next thing learned &#9654;</button>
    <button id="play" class="primary">${playTimer ? 'Stop' : 'Play'}</button>
    <a href="#/precedents/${i.id}">Was this seen before?</a> · <a href="#/timeline/${encodeURIComponent(i.element)}">Timeline of ${esc(i.element)}</a></div>
  <h2>How knowledge about this incident arrived</h2>
  <p class="muted small">Each entry is drawn twice: when it happened (top) and when the Record learned of it (bottom). A steep line was known at once; a long slanted line was written much later. The time scale is compressed: each step to the right is about ten times longer.</p>
  <div class="key">${roles.map((r) => `<span><i class="${ROLE_CLASS[r]}"></i>${ROLE_LABEL[r] || r}</span>`).join('')}</div>
  <div id="know"></div>
  <h2>Entries attached (${d.entries.length} known at this time)</h2>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}<th>Delay</th></tr>${d.entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}"><td>${esc(e.role)}</td>
    <td class="t">${fmt(e.t_start)}</td><td class="t">${fmt(e.known_at)}</td><td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td><td class="what">${esc(describe(e))}</td><td class="t">${dur(e.known_at - e.t_start)}</td></tr>`).join('')}</table></div>
  <h2>Expert reasoning ${EXPERT}</h2>
  ${d.links.filter((l) => l.link_type === 'indirect').length ? '<ul>' + d.links.filter((l) => l.link_type === 'indirect').map((l) => `<li>entry ${entryLink(l.src_entry_id)} ${esc(l.relation)} entry ${entryLink(l.dst_entry_id)}: ${esc(l.rationale)} <span class="muted small">(known ${fmt(l.known_at)})</span></li>`).join('') + '</ul>' : '<p class="muted">No expert links are known at this time.</p>'}`;
  return { html, mount() {
    $('#know').innerHTML = knowledgeChart(i, d.entries, $('#know').clientWidth);
    const step = async (direction) => {
      const r = await api('next_known', { t: S.asOf, direction, incident: i.id }, false);
      if (r.t == null || (direction === 'previous' && r.t < i.known_at)) { if (playTimer) { stopPlay(); render(); } return false; }
      setAsOf(r.t); return true;
    };
    $('#play-prev').addEventListener('click', () => step('previous'));
    $('#play-next').addEventListener('click', () => step('next'));
    $('#play').addEventListener('click', () => {
      if (playTimer) { stopPlay(); render(); return; }
      playTimer = setInterval(() => step('next'), 1600);
      setAsOf(i.known_at);
      render();
    });
  } };
};
function stopPlay() { if (playTimer) { clearInterval(playTimer); playTimer = null; } }

const TL = { t0: null, t1: null, typical: false };
PAGES.timeline = async (parts) => {
  const name = parts[1] ? decodeURIComponent(parts[1]) : (S.elements.find((e) => e.kind === 'readout_box') || S.elements[0]).name;
  const d = await api('timeline', { element: name });
  if (TL.t0 == null) { TL.t0 = d.t0; TL.t1 = d.t1; }
  const kinds = ['subdetector', 'readout_box', 'lv_supply', 'fed', 'detector'];
  const html = `<h1>Timeline of ${esc(name)}</h1>
  <p class="muted">Readings from ${d.boxes.map(esc).join(', ')}${d.n_boxes > d.boxes.length ? ` (first ${d.boxes.length} of ${d.n_boxes} readout boxes)` : ''}, and what was recorded about ${esc(name)} and its surroundings, as known at the time control.</p>
  <div class="filters">
    <label>Element <select id="tl-el">${kinds.map((k) => `<optgroup label="${k.replace('_', ' ')}">${S.elements.filter((e) => e.kind === k).map((e) => `<option${e.name === name ? ' selected' : ''}>${esc(e.name)}</option>`).join('')}</optgroup>`).join('')}</select></label>
    <button data-tl="in">Zoom in</button><button data-tl="out">Zoom out</button><button data-tl="left">&#9664;</button><button data-tl="right">&#9654;</button>
    <button data-tl="all">Whole calendar</button><button data-tl="clock">12 h before the time control</button>
    <label><input type="checkbox" id="tl-typ"${TL.typical ? ' checked' : ''}> Vertical scale: typical range</label>
  </div>
  <p class="muted small">Drag across the chart to zoom into a time range; double-click to see the whole calendar. "Typical range" ignores the most extreme 5% at each end, so a small drift stays visible next to a trip to zero. Click a mark to open its entry.</p>
  ${d.boxes.length > 1 ? `<div class="key">${d.boxes.map((b, k) => `<span><i class="c${k + 1}"></i>${esc(b)}</span>`).join('')}</div>` : ''}
  <div id="tl"></div>`;
  const rowsOf = () => d.strip.map((r) => ({ label: r.row, items: r.items.map((it) => ({
    t0: it.t0, ...(r.row === 'Stable beams' || r.row === 'Downtime' || r.row === 'Certified bad' ? { t1: it.t1 ?? null } : {}),
    cls: { 'Stable beams': 'beam', Downtime: 'down', 'Certified bad': 'bad', 'State change': 'mk', 'Fault event': it.planned ? 'mk' : 'mk crit', 'Logbook note': it.routine ? 'note routine' : 'note' }[r.row],
    shape: { 'State change': 'diamond', 'Fault event': 'tri', 'Logbook note': 'tick' }[r.row],
    tip: `${fmt(it.t0)}\n${it.text}`, go: `#/entry/${it.id}` })) }));
  return { html, mount() {
    const host = $('#tl');
    const draw = () => {
      const cfg = { t0: TL.t0, t1: TL.t1, width: host.clientWidth, typical: TL.typical, panels: d.panels, rows: rowsOf(),
        vlines: d.incidents.map((i) => ({ t: i.t_start, cls: 'inc', label: `#${i.id}`, tip: `${i.title} (${i.status})`, go: `#/incident/${i.id}` })).concat([{ t: S.asOf, cls: 'asof' }]),
        aria: `readings and recorded events for ${name}` };
      const chart = buildChart(cfg);
      host.innerHTML = chart.svg;
      wireChart(host, chart, cfg, { zoom: (a, b) => { TL.t0 = a; TL.t1 = b; draw(); }, reset: () => { TL.t0 = d.t0; TL.t1 = d.t1; draw(); } });
    };
    draw();
    $('#tl-el').addEventListener('change', (ev) => { location.hash = `#/timeline/${encodeURIComponent(ev.target.value)}`; });
    $('#tl-typ').addEventListener('change', (ev) => { TL.typical = ev.target.checked; draw(); });
    document.querySelectorAll('[data-tl]').forEach((b) => b.addEventListener('click', () => {
      const w = TL.t1 - TL.t0, mid = (TL.t0 + TL.t1) / 2, a = b.dataset.tl;
      if (a === 'in') { TL.t0 = mid - w / 4; TL.t1 = mid + w / 4; }
      if (a === 'out') { TL.t0 = mid - w; TL.t1 = mid + w; }
      if (a === 'left') { TL.t0 -= w / 3; TL.t1 -= w / 3; }
      if (a === 'right') { TL.t0 += w / 3; TL.t1 += w / 3; }
      if (a === 'all') { TL.t0 = d.t0; TL.t1 = d.t1; }
      if (a === 'clock') { TL.t1 = Math.min(S.asOf, d.t1) + 3600; TL.t0 = TL.t1 - 13 * 3600; }
      TL.t0 = Math.round(Math.max(d.t0 - 86400, TL.t0)); TL.t1 = Math.round(Math.min(d.t1 + 86400, TL.t1));
      draw();
    }));
  } };
};

async function plantedModes() {
  if (!showPlanted()) return null;
  if (!S.plantedData) S.plantedData = await api('demo/planted', {}, false);
  return Object.fromEntries(S.plantedData.planted.filter((c) => c.incident_id).map((c) => [c.incident_id, c.mode]));
}
PAGES.precedents = async (parts) => {
  const modes = await plantedModes();
  const intro = `<p>When a problem appears, the crew asks "has this been seen before?". There are two candidate rules for what counts as a precedent. Both are computed only from what is in the Record: the entries people attached to earlier incidents as symptoms.</p>
  <ul><li><b>Same element:</b> an earlier incident on the same element.</li><li><b>Same symptom:</b> an earlier incident on any element whose symptom entries are of the same kind.</li></ul>`;
  const precRows = (rows) => rows.length ? `<div class="tablewrap"><table><tr><th>#</th><th>Started</th><th>Element</th><th>Title</th><th>Status then</th><th>Recovery known then</th><th>Cause known then</th>${modes ? `<th class="demo-col">Planted mode ${DEMO}</th>` : ''}</tr>
    ${rows.map((r) => `<tr class="click" data-go="#/incident/${r.id}"><td class="num">${r.id}</td><td class="t">${fmt(r.t_start)}</td><td>${esc(r.element)}</td><td>${esc(r.title)}</td><td>${statusCell(r.status)}</td>
      <td class="what">${r.recovery_action ? esc(r.recovery_action) : unknown}</td><td class="what">${r.confirmed_cause ? esc(r.confirmed_cause) : unknown}</td>${modes ? `<td class="demo-col">${esc(modes[r.id] || '')}</td>` : ''}</tr>`).join('')}</table></div>` : '<p class="muted">None.</p>';
  if (parts[1]) {
    const d = await api('precedents', { id: parts[1] });
    if (d.error) return { html: `<h1>Precedents</h1><p>${esc(d.error)}</p>` };
    const p = d.problem;
    return { html: `<h1>Was incident #${p.id} seen before?</h1>${intro}
      <div class="card"><dl class="facts"><dt>Problem</dt><dd>${incLink(p.id, p.title)} on ${esc(p.element)}</dd>
        <dt>Crew asks at</dt><dd>${fmt(d.ask_time)} <span class="muted">(5 min after the first symptom reached the Record)</span> ${asofBtn(d.ask_time, 'go to this moment')}</dd>
        <dt>Symptom kinds</dt><dd class="mono">${d.symptom_kinds.map(esc).join(', ') || 'none'}</dd>
        ${modes ? `<dt class="demo-col">Planted mode ${DEMO}</dt><dd class="demo-col">${esc(modes[p.id] || '')}</dd>` : ''}</dl></div>
      <p class="muted small">Earlier incidents are shown as the Record knew them at the moment the crew asks, not as they are known now.</p>
      <h2>Rule A: same element (${d.same_element.length})</h2>${precRows(d.same_element)}
      <h2>Rule B: same symptom anywhere (${d.same_symptom.length})</h2>${precRows(d.same_symptom)}
      <p><a href="#/precedents">All incidents under both rules</a></p>` };
  }
  const d = await api('precedents');
  const list = (ids) => (ids.length ? ids.map((x) => `#${x}`).join(' ') : '<span class="muted">none</span>');
  const html = `<h1>Precedents: two rules compared</h1>${intro}
  <div class="card"><b>Across the ${d.incidents.length} incidents known at this time</b>
    <dl class="facts"><dt>Called "seen before" by same element</dt><dd><b>${d.known_by_same_element}</b></dd>
    <dt>Called "seen before" by same symptom</dt><dd><b>${d.known_by_same_symptom}</b></dd>
    <dt>The two rules disagree on</dt><dd><b>${d.disagree}</b></dd></dl>
    <p class="muted small">Each incident is judged at the moment its crew would have asked, with only what the Record knew then. The tiny preset has few recurrences; build the small preset to see the rules disagree.</p></div>
  <div class="tablewrap"><table><tr><th>#</th><th>Started</th><th>Element</th><th>Title</th><th>Symptom kinds</th><th>Same element</th><th>Same symptom</th>${modes ? `<th class="demo-col">Planted mode ${DEMO}</th>` : ''}</tr>
  ${d.incidents.map((r) => `<tr class="click" data-go="#/precedents/${r.id}"><td class="num">${r.id}</td><td class="t">${fmt(r.t_start)}</td><td>${esc(r.element)}</td><td>${esc(r.title)}</td><td class="mono">${r.symptom_kinds.map(esc).join(', ')}</td>
    <td>${list(r.same_element)}</td><td>${list(r.same_symptom)}</td>${modes ? `<td class="demo-col">${esc(modes[r.id] || '')}</td>` : ''}</tr>`).join('')}</table></div>`;
  return { html };
};

const READS = {
  entries: ['Entries known at the time control whose event time overlaps a window.', ['elements', 'types', 'kinds', 'record_classes', 'sources', 'text', 't0', 't1', 'limit']],
  state_at: ['The last state of one type on an element at or before a time, however old.', ['element', 'type', 't']],
  incidents: ['All incidents known at the time control, open and closed.', ['elements']],
  incident: ['One incident as the Record knew it.', ['incident_id']],
  incident_entries: ['The entries attached to an incident, with their roles.', ['incident_id']],
  links: ['Links touching an entry. Both ends must be known.', ['entry_id']],
  related: ['Service-side neighbours of an element: its supply, its FED, or the boxes it serves.', ['element']],
  subtree: ['An element and everything below it.', ['element']],
  ancestors: ['Everything above an element.', ['element']],
};
const HINT = { elements: 'HFP02,HF', types: 'lv_voltage', kinds: 'state,point', record_classes: 'MS,QA,HI', sources: 'dcs,elog', text: 'configure', t0: 'time', t1: 'time', t: 'time', limit: '50', element: 'HFP02', type: 'control_link', incident_id: '3', entry_id: '28' };
const RA = { method: 'state_at', values: {}, out: null };
PAGES.api = async () => {
  const [doc, args] = READS[RA.method];
  const html = `<h1>Read API</h1>
  <p class="muted">Run the Record's own read methods by hand. These are the calls every page here makes, and the calls the agent's tools will be built on. The time control is passed as <code>as_of</code> to every call that reads content.</p>
  <div class="filters"><label>Method <select id="ra-m">${Object.keys(READS).map((m) => `<option${m === RA.method ? ' selected' : ''}>${m}</option>`).join('')}</select></label><span class="muted">${doc}</span></div>
  <div class="filters">${args.map((a) => `<label>${a} <input type="text" data-ra="${a}" value="${esc(RA.values[a] || '')}" placeholder="${HINT[a] || ''}" size="${a === 'text' || a === 'elements' ? 18 : 12}"></label>`).join('')}
    <button class="primary" id="ra-run">Run</button></div>
  <p class="muted small">Lists are comma-separated. Times may be typed as 2040-03-02 00:05 or left empty.</p>
  <div id="ra-out">${RA.out || ''}</div>`;
  return { html, mount() {
    $('#ra-m').addEventListener('change', (ev) => { RA.method = ev.target.value; RA.out = null; render(); });
    const run = async () => {
      const params = { method: RA.method };
      document.querySelectorAll('[data-ra]').forEach((el) => {
        RA.values[el.dataset.ra] = el.value;
        if (!el.value) return;
        params[el.dataset.ra] = ['t', 't0', 't1'].includes(el.dataset.ra) && Number.isNaN(+el.value) ? parseT(el.value) : el.value;
      });
      try {
        const r = await api('read', params);
        const rows = Array.isArray(r.result) ? r.result : r.result == null ? [] : [r.result];
        const isEntry = (x) => x && typeof x === 'object' && 'payload' in x;
        let body;
        if (r.result == null) body = '<p><b>None.</b> Nothing matches at this time.</p>';
        else if (rows.length && rows.every(isEntry)) body = `<div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows(rows)}</table></div>`;
        else if (rows.length && rows.every((x) => Array.isArray(x) && isEntry(x[1]))) body = `<div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}</tr>${entryRows(rows.map((x) => x[1]), (e) => `<td>${esc(rows.find((x) => x[1].id === e.id)[0])}</td>`)}</table></div>`;
        else body = `<pre>${esc(JSON.stringify(r.result, null, 2))}</pre>`;
        RA.out = `<h2>Call</h2><pre>${esc(r.call)}</pre><h2>Returned ${Array.isArray(r.result) ? r.result.length + ' rows' : ''}</h2>${body}`;
      } catch (e) { RA.out = `<p><b>Error:</b> ${esc(e.message)}</p>`; }
      $('#ra-out').innerHTML = RA.out;
    };
    $('#ra-run').addEventListener('click', run);
    document.querySelectorAll('[data-ra]').forEach((el) => el.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') run(); }));
  } };
};

const DV = { mode: null, idx: 0 };
PAGES.device = async () => {
  if (!showDemo()) return { html: '<h1>Device and faults</h1><p>This page is demo only and is hidden in production view.</p>' };
  const d = await api('demo/device', {}, false);
  const modes = Object.keys(d.modes).filter((m) => d.cases.some((c) => c.mode === m));
  if (!modes.includes(DV.mode)) { DV.mode = modes[0]; DV.idx = 0; }
  const cases = d.cases.filter((c) => c.mode === DV.mode);
  const c = cases[Math.min(DV.idx, cases.length - 1)];
  const tree = (parent) => {
    const kids = S.elements.filter((e) => e.parent === parent && e.kind !== 'channel');
    if (!kids.length) return '';
    return '<ul>' + kids.map((e) => {
      const rel = e.related.filter(([r]) => !r.endsWith('_of')).map(([r, n]) => `${r.replace(/_/g, ' ')} ${n}`).join(', ');
      const serves = e.related.filter(([r]) => r.endsWith('_of')).map(([, n]) => n).join(', ');
      const nch = S.elements.filter((x) => x.parent === e.name && x.kind === 'channel').length;
      return `<li>${elLink(e.name)} <span class="muted small">${e.kind.replace('_', ' ')}${nch ? `, ${nch} channels` : ''}${rel ? ' · ' + rel : ''}${serves ? ' · serves ' + serves : ''}</span>${tree(e.name)}</li>`;
    }).join('') + '</ul>';
  };
  const html = `${demoBand('This page shows the generator\'s own view of the data. It ignores the time control on purpose: it lists when each piece <i>will</i> become known. Nothing here would exist for a real detector.')}
  <h1>Device and faults</h1>
  <h2>Fault catalogue</h2>
  <p class="muted">Each planted situation, what its script wrote into the Record, when each piece happened and when the Record learns of it. This is the page for judging whether the synthetic data is plausible.</p>
  <div class="tabs">${modes.map((m) => `<button data-dv-mode="${m}" class="${m === DV.mode ? 'on' : ''}">${esc(d.modes[m].title)} (${d.cases.filter((x) => x.mode === m).length})</button>`).join('')}</div>
  <div class="card"><b>${esc(d.modes[DV.mode].title)}</b><p>${esc(d.modes[DV.mode].story)}</p></div>
  <div class="tabs">${cases.map((x, k) => `<button data-dv-idx="${k}" class="${x.id === c.id ? 'on' : ''}">${x.id} · ${esc(x.true_element)} · ${fmtShort(x.t_event)}</button>`).join('')}</div>
  <div class="card"><dl class="facts">
    <dt>Where the fault really is</dt><dd>${elLink(c.true_element)}</dd><dt>What the crew sees it on</dt><dd>${esc(c.reported_element)}</dd>
    <dt>Starts</dt><dd>${fmt(c.t_event)} ${asofBtn(c.ask_at, 'set the time control to when the crew asks')}</dd>
    <dt>Incident in the Record</dt><dd>${c.incident ? incLink(c.incident.id, c.incident.title) + ` (finally ${c.incident.status})` : 'none: this is not a fault'}</dd>
    <dt>Crew's question</dt><dd>${esc(c.question)}</dd>
    <dt>Honest answer then</dt><dd>${esc(c.expected.verdict)}; next step: ${esc(c.expected.next_step.replace('_', ' '))}${c.expected.precedents.length ? '; precedents ' + c.expected.precedents.map((x) => '#' + x).join(' ') : ''}</dd>
  </dl></div>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}<th>Delay</th></tr>${c.entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}"><td>${esc(e.role)}</td>
    <td class="t">${fmt(e.t_start)}</td><td class="t">${fmt(e.known_at)}</td><td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td><td class="what">${esc(describe(e))}</td><td class="t">${dur(e.known_at - e.t_start)}</td></tr>`).join('')}</table></div>
  <p class="muted small">Opening an entry or incident from here uses the time control; if it says "not known", move the time forward.</p>
  <h2>Detector map</h2><div class="card tree">${tree(null)}</div>
  <h2>Calendar</h2>
  <details><summary>${d.runs.length} runs in ${new Set(d.runs.map((r) => r.fill)).size} fills</summary><div class="tablewrap"><table><tr><th class="num">Run</th><th class="num">Fill</th><th>Start</th><th>End</th><th class="num">Lumisections</th><th>Why it stopped</th></tr>
  ${d.runs.map((r) => `<tr><td class="num">${r.run}</td><td class="num">${r.fill}</td><td class="t">${fmt(r.t0)}</td><td class="t">${fmt(r.t1)}</td><td class="num">${r.n_ls}</td><td>${esc(r.reason.replace(/_/g, ' '))}</td></tr>`).join('')}</table></div></details>`;
  return { html, mount() {
    document.querySelectorAll('[data-dv-mode]').forEach((b) => b.addEventListener('click', () => { DV.mode = b.dataset.dvMode; DV.idx = 0; render(); }));
    document.querySelectorAll('[data-dv-idx]').forEach((b) => b.addEventListener('click', () => { DV.idx = +b.dataset.dvIdx; render(); }));
  } };
};

PAGES.planted = async () => {
  if (!showDemo()) return { html: '<h1>Planted answers</h1><p>This page is demo only and is hidden in production view.</p>' };
  const d = await api('demo/planted', {}, false);
  const html = `${demoBand('The generator\'s hidden list of what it planted and the honest answer at each moment. It is kept in a separate file and is never part of the Record. The agent will never read it.')}
  <h1>Planted answers</h1>
  <p class="muted">"Ask time" is when a crew would ask about the problem. "Expected" is what an honest answer is with only what the Record knew then.</p>
  <div class="tablewrap"><table><tr><th>Case</th><th>Mode</th><th>Really on</th><th>Crew sees</th><th>Event</th><th>Ask time</th><th>Expected verdict</th><th>Next step</th><th>Precedents</th><th>Incident</th><th></th></tr>
  ${d.planted.map((c) => `<tr><td>${c.id}</td><td>${esc(c.mode)}</td><td>${elLink(c.true_element)}</td><td>${esc(c.reported_element)}</td><td class="t">${fmt(c.t_event)}</td><td class="t">${fmt(c.ask_at)}</td>
    <td><b>${esc(c.expected.verdict.replace(/_/g, ' '))}</b></td><td>${esc(c.expected.next_step.replace(/_/g, ' '))}</td><td>${c.expected.precedents.map((x) => incLink(x)).join(' ') || '<span class="muted">none</span>'}</td>
    <td>${c.incident_id ? incLink(c.incident_id) : '<span class="muted">none</span>'}</td><td>${asofBtn(c.ask_at, 'go to ask time')}</td></tr>`).join('')}</table></div>
  <p class="muted small">Here a precedent is any earlier planted case of the same mode. Compare with the two Record-only rules on the <a href="#/precedents">Precedents</a> page, with "Show planted answers" switched on.</p>`;
  return { html };
};

/* ----------------------------------------------------------------- shell */
let token = 0;
async function render() {
  const my = ++token;
  const parts = (location.hash.split('?')[0].replace(/^#\/?/, '') || 'home').split('/');
  const page = PAGES[parts[0]] ? parts[0] : 'home';
  if (page !== 'incident') stopPlay();
  drawNav(page);
  updateClock();
  $('#sw-planted-wrap').hidden = !showDemo();
  const main = $('#main');
  try {
    const out = await PAGES[page](parts);
    if (my !== token) return;
    main.innerHTML = out.html;
    if (out.mount) out.mount();
  } catch (e) {
    if (my !== token) return;
    main.innerHTML = `<h1>Nothing to show</h1><p>${esc(e.message)}</p><p class="muted">The time control is at ${fmt(S.asOf)}. If this entry or incident was learned later, move the time forward.</p>
      <p><button data-asof="${S.meta.latest_known_at}">Go to "everything known"</button></p>`;
  }
}
document.addEventListener('click', (ev) => {
  const a = ev.target.closest('[data-asof]');
  if (a) { ev.stopPropagation(); setAsOf(+a.dataset.asof); return; }
  const g = ev.target.closest('[data-go]');
  if (g && !ev.target.closest('a,button')) {
    if (g.dataset.filter) Object.assign(RF, { cls: '', source: '', type: '', kind: '', element: '', q: '', offset: 0 }, JSON.parse(g.dataset.filter));
    location.hash = g.dataset.go;
  }
});
document.addEventListener('mousemove', (ev) => {
  const t = ev.target.closest && ev.target.closest('[data-tip]');
  if (t && t.dataset.tip) showTip(t.dataset.tip, ev);
  else if (!ev.target.closest || !ev.target.closest('#tl svg, #cal svg')) hideTip();
});
window.addEventListener('hashchange', () => {
  const m = location.hash.match(/[?&]t=(\d+)/);
  if (m && +m[1] !== S.asOf) { S.prev = S.asOf; S.asOf = +m[1]; } else if (!m) syncHash();
  render(); window.scrollTo(0, 0);
});
let resizeTimer = null;
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 200); });

(async function start() {
  S.meta = await api('meta', {}, false);
  $('#banner').title = S.meta.banner;
  const m = location.hash.match(/[?&]t=(\d+)/);
  S.asOf = m ? +m[1] : S.meta.latest_known_at;
  S.prod = store('prod') === '1'; S.planted = store('planted') === '1';
  $('#sw-prod').checked = S.prod; $('#sw-planted').checked = S.planted;
  $('#sw-prod').addEventListener('change', (ev) => { S.prod = ev.target.checked; store('prod', S.prod ? '1' : '0'); render(); });
  $('#sw-planted').addEventListener('change', (ev) => { S.planted = ev.target.checked; store('planted', S.planted ? '1' : '0'); render(); });
  S.elements = (await api('elements')).elements;
  wireClock();
  if (!location.hash) location.hash = '#/home'; else syncHash();
  render();
})();
