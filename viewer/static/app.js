'use strict';
/* Operations Record browser.
   Every number shown comes from the local service, which calls the Record's own read
   methods. Normally the whole Record is shown. In a replay, every read is made "as of"
   the replay's moment and nothing later is shown. This file only draws. */

const S = { meta: null, asOf: 0, replay: null, elements: [], planted: null, reveal: false };
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/* Timestamps: a short form on screen ("Mar 2 12:06"), the full one on hover. */
const fmtFull = (t) => (t == null ? '–' : new Date(t * 1000).toISOString().slice(0, 19).replace('T', ' ') + ' UTC');
const fmt = (t) => {
  if (t == null) return '–';
  const d = new Date(t * 1000);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
};
const tm = (t) => (t == null ? '–' : `<span class="ts" title="${fmtFull(t)}">${fmt(t)}</span>`);
const fmtShort = fmt;
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
async function api(route, params = {}, withAsOf = true) {
  const q = new URLSearchParams(withAsOf ? { as_of: S.asOf, ...params } : params);
  const r = await fetch(`/api/${route}?${q}`);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || `request failed (${r.status})`);
  return j;
}
function describe(e) {
  const p = e.payload || {};
  if (p.text) return `${p.author_role || '?'}: ${p.text}`;
  if (e.type === 'quality_status') return `quality ${p.value} (run ${p.run}: occupancy ${p.mean_occupancy} vs reference ${p.reference}, hot ${p.hot_fraction}, worst-lumisection dead ${p.worst_ls_dead_fraction})`;
  if (e.type === 'quality_reference') return `occupancy reference ${p.value}: ${p.reason}`;
  if (e.type.endsWith('_status')) return `${e.type.replace('_status', '').replace('_', ' ')} ${p.value} (reading ${p.reading} ${p.unit}, setpoint ${p.reference})`;
  if (e.type === 'downtime') return `${Math.floor(p.duration_s / 60)} min, ${p.lost_lumi_pb} /pb lost, ${p.category}: ${p.details}`;
  return Object.entries(p).map(([k, v]) => `${k}=${Array.isArray(v) ? JSON.stringify(v) : v}`).join(', ');
}
/* An empty label means "never recorded" normally, and "not known yet" during a replay. */
const empty = () => `<span class="unknown">${S.replay ? 'not known yet' : 'none recorded'}</span>`;
const entryLink = (id) => `<a href="#/entry/${id}">${id}</a>`;
const elLink = (name) => `<a href="#/timeline/${encodeURIComponent(name)}">${esc(name)}</a>`;
const incLink = (id, title) => `<a href="#/incident/${id}">#${id}${title ? ' ' + esc(title) : ''}</a>`;
const CLASS_NAME = { MS: 'Machine state', QA: 'Quality assurance', HI: 'Human interpretation' };
const clsTag = (c) => `<span class="cls cls-${c}" title="${CLASS_NAME[c] || c}">${c}</span>`;
const ROLE_ORDER = ['filed', 'reported', 'mentioned', 'affected', 'suspected', 'cause'];
function partsTable(parts) {
  if (!parts || !parts.length) return `<p class="muted">None ${S.replay ? 'known yet' : 'recorded'}.</p>`;
  const sorted = [...parts].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || a.known_at - b.known_at);
  return `<div class="tablewrap"><table><tr><th>Role</th><th>Part</th><th>Known to the Record</th><th>Said by</th><th>Status</th></tr>${sorted.map((r) =>
    `<tr><td><span class="role role-${r.role}">${r.role}</span></td><td>${elLink(r.element)}</td><td class="t">${tm(r.known_at)}</td><td class="mono small">${esc(r.producer)}</td><td>${r.status}</td></tr>`).join('')}</table></div>`;
}
const statusCell = (s) => `<span class="status">${s}</span>`;
const ENTRY_HEAD = '<th>Happened</th><th>Known to the Record</th><th class="num">id</th><th>Class</th><th>Source / type</th><th>Element</th><th>What</th>';
function entryRows(entries, extra) {
  return entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}">
    ${extra ? extra(e) : ''}<td class="t">${tm(e.t_start)}</td><td class="t">${tm(e.known_at)}</td>
    <td class="num">${e.id}</td><td>${clsTag(e.record_class)}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td>
    <td class="what">${esc(describe(e))}</td></tr>`).join('');
}

/* ------------------------------------------------------------------------ replay */
let playTimer = null;
function stopPlay() { if (playTimer) { clearInterval(playTimer); playTimer = null; } }
async function startReplay(id) {
  const end = S.meta.latest_known_at;
  const d = await (await fetch(`/api/replay?id=${id}&as_of=${end}`)).json();
  S.replay = { id, title: d.frame.title, ask: d.ask_time, opened: d.frame.opened_at, steps: d.steps, prev: null };
  S.asOf = d.ask_time;
  location.hash = '#/replay';
  syncHash(); render();
}
function startFreeReplay(t) {            // look at a moment without following an incident
  S.replay = { id: null, title: null, ask: t, opened: null, steps: null, prev: null };
  S.asOf = t; location.hash = '#/replay'; syncHash(); render();
}
function exitReplay() { stopPlay(); S.replay = null; S.asOf = S.meta.latest_known_at; syncHash(); render(); }
function setAsOf(t) {
  if (!S.replay) return;
  t = Math.max(S.meta.t0, Math.min(S.meta.latest_known_at, Math.round(t)));
  if (t === S.asOf) return;
  S.replay.prev = S.asOf; S.asOf = t; syncHash(); render();
}
async function step(direction) {
  const r = S.replay;
  let t;
  if (r.steps) t = direction === 'next' ? r.steps.find((x) => x > S.asOf) : [...r.steps].reverse().find((x) => x < S.asOf);
  else t = (await api('next_known', { t: S.asOf, direction }, false)).t;
  if (t == null) { if (playTimer) { stopPlay(); render(); } return; }
  setAsOf(t);
}
function syncHash() {
  const path = location.hash.split('?')[0] || '#/detector';
  history.replaceState(null, '', S.replay ? `${path}?r=${S.replay.id ?? 'free'}&t=${S.asOf}` : path);
}
function drawBar() {
  const bar = $('#replay-bar');
  bar.hidden = !S.replay;
  if (!S.replay) return;
  const r = S.replay;
  bar.innerHTML = `<div class="clock-row"><b>${r.id ? `Replay of incident #${r.id} is on.` : 'Looking at a past moment.'}</b>
    <span>Every page shows the Record as it stood at <b>${tm(S.asOf)}</b> UTC, and nothing learned later.</span>
    <span class="spacer"></span><a href="#/replay">Back to the replay</a><button id="rp-exit">Exit replay</button></div>`;
  $('#rp-exit').addEventListener('click', exitReplay);
}
/* the step controls, shown on the replay page itself */
function stepControls() {
  const r = S.replay;
  const done = r.steps ? r.steps.filter((x) => x <= S.asOf).length : null;
  return `<div class="filters stepper"><button id="rp-prev">&#9664; previous step</button><button id="rp-next" class="primary">next step &#9654;</button>
    ${r.steps ? `<button id="rp-play">${playTimer ? 'Stop' : 'Play'}</button><span class="muted">step ${done} of ${r.steps.length}</span>` : ''}
    <span class="spacer"></span><span class="muted small">Jump to:</span>
    ${r.id ? `<button data-asof="${r.ask}" title="Five minutes after the first symptom reached the Record">when the crew asks</button>` : ''}
    ${r.opened ? `<button data-asof="${r.opened}">incident opened</button>` : ''}
    <button data-asof="${S.meta.latest_known_at}">everything known</button></div>`;
}
function wireSteps() {
  $('#rp-prev').addEventListener('click', () => step('previous'));
  $('#rp-next').addEventListener('click', () => step('next'));
  if ($('#rp-play')) $('#rp-play').addEventListener('click', () => {
    if (playTimer) { stopPlay(); render(); return; }
    playTimer = setInterval(() => step('next'), 1800); render();
  });
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
  for (const s of panel.series) for (const p of s.points) {
    if (p.t1 < t0 || p.t0 > t1) continue;
    vs.push(p.v);
    lo = Math.min(lo, p.v);
    hi = Math.max(hi, p.v);
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
      const cls = s.cls || `c${i + 1}`;
      const pts = s.points.filter((q) => q.t1 >= cfg.t0 && q.t0 <= cfg.t1);
      if (p.per_run) {
        for (const q of pts) marks += `<line class="line ${cls}" x1="${X(q.t0)}" x2="${X(q.t1)}" y1="${Y(q.v)}" y2="${Y(q.v)}"/>`;
        return;
      }
      let d = '', prev = null;
      for (const q of pts) {
        const xm = X((q.t0 + q.t1) / 2);
        const gap = prev && q.t0 - prev.t1 > 1.5 * (q.t1 - q.t0);
        d += `${prev && !gap ? 'L' : 'M'}${xm.toFixed(1)},${Y(q.v).toFixed(1)}`;
        prev = q;
      }
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
      const t1 = it.t1 === undefined ? undefined : (it.t1 ?? Math.min(cfg.t1, S.asOf));   // still going: draw it up to the current moment, not beyond
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
  let lines = '', lastLabel = -1e9;
  for (const v of cfg.vlines || []) {
    if (v.t < cfg.t0 || v.t > cfg.t1) continue;
    lines += `<line class="${v.cls}" x1="${X(v.t)}" x2="${X(v.t)}" y1="20" y2="${bottom}"/>`;
    if (v.label && X(v.t) - lastLabel >= 26) {         // labels too close to the previous one are left out; zoom in to see them
      lines += `<text class="hit" x="${X(v.t)}" y="13" text-anchor="middle" data-tip="${esc(v.tip || '')}"${v.go ? ` data-go="${v.go}"` : ''}>${esc(v.label)}</text>`;
      lastLabel = X(v.t);
    }
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


/* --------------------------------------------------------- detector map */
const NORMAL = new Set(['on', 'ok', 'normal', 'STABLE BEAMS', 'NO BEAM', 'TECHNICAL STOP']);
const stateName = (k) => k.replace('_status', '').replace(/_/g, ' ');
const SHORT = { control_link: 'link', lv_voltage_status: 'LV', temperature_status: 'temp', quality_status: 'quality', quality_reference: 'reference', supply_state: 'supply', beam_mode: 'beam' };
const shortName = (k) => SHORT[k] || stateName(k);
function mapSvg(d, width) {
  const W = Math.max(760, width), SW = 170, FW = 170, SX = 16, FX = W - FW - 16, BX = SX + SW + 70, BW = FX - 70 - BX, RH = 50, GAP = 10;
  const by = Object.fromEntries(d.elements.map((e) => [e.name, e]));
  const kids = (parent, kind) => d.elements.filter((e) => e.parent === parent && e.kind === kind);
  const rel = (e, r) => e.related.filter(([x]) => x === r).map(([, n]) => n);
  const hot = Object.fromEntries(d.flags.map((f) => [f.element, f]));
  const issues = {};
  for (const i of d.open_issues) {
    for (const el of new Set([i.element, ...(i.parts || []).map((x) => x.element)])) (issues[el] = issues[el] || []).push(i);
  }
  let y = 8, body = '', wires = '';
  const node = (e, x, yy, w, h, extra) => {
    const st = Object.entries(e.states);
    const bad = st.some(([, v]) => !NORMAL.has(v.value));
    const tip = [`${e.name} (${e.kind.replace('_', ' ')})`].concat(st.map(([k, v]) => `${k.replace('_', ' ')}: ${v.value} since ${fmt(v.since)}`),
      (issues[e.name] || []).map((i) => `open issue #${i.id}: ${i.title} (${i.status})`)).join('\n');
    let g = `<g class="hit" data-go="#/timeline/${encodeURIComponent(e.name)}" data-tip="${esc(tip)}">
      <rect x="${x}" y="${yy}" width="${w}" height="${h}" rx="6" class="node${bad ? ' bad' : ''}"/>
      <text class="title" x="${x + 10}" y="${yy + 18}">${esc(e.name)}</text>
      <text x="${x + 10}" y="${yy + 34}">${st.map(([k, v]) => `<tspan class="${NORMAL.has(v.value) ? '' : 'st-bad'}">${shortName(k)} ${esc(v.value)}</tspan>`).join(' · ')}</text>${extra || ''}</g>`;
    (issues[e.name] || []).forEach((i, k) => {
      g += `<text class="hit issue" x="${x + w - 8}" y="${yy + 18 + 14 * k}" text-anchor="end" data-go="#/incident/${i.id}" data-tip="${esc(i.title + ' (' + i.status + ')')}">open issue #${i.id}</text>`;
    });
    return g;
  };
  const centre = {};
  for (const exp of d.elements.filter((e) => e.kind === 'experiment')) {
    for (const det of kids(exp.name, 'detector')) {
      for (const sub of kids(det.name, 'subdetector')) {
        const boxes = kids(sub.name, 'readout_box');
        const top = y;
        body += `<text class="title" x="${BX}" y="${y + 14}">${esc(sub.name)}</text>` +
          (issues[sub.name] || []).map((i, k) => `<text class="hit issue" x="${BX + 40 + k * 100}" y="${y + 14}" data-go="#/incident/${i.id}">open issue #${i.id}</text>`).join('');
        y += 24;
        for (const b of boxes) {
          const chans = kids(b.name, 'channel');
          // the left part of the box is for its name and states; channels start after it
          const CX = BX + Math.max(260, Math.min(330, BW * 0.45));
          const cw = Math.max(3, Math.min(11, (BX + BW - 16 - CX) / Math.max(1, chans.length)));
          const cells = chans.map((c, k) => `<rect class="${hot[c.name] ? 'chan hot' : 'chan'}" x="${CX + k * cw}" y="${y + RH - 25}" width="${cw - 2}" height="9"><title>${esc(c.name)}${hot[c.name] ? ': flagged ' + hot[c.name].flag : ''}</title></rect>`).join('');
          const nhot = chans.filter((c) => hot[c.name]).length;
          body += node(b, BX, y, BW, RH - GAP, cells + `<text x="${CX}" y="${y + 18}">${chans.length} channels${nhot ? `, ${nhot} flagged hot` : ''}</text>` +
            `<line class="grid" x1="${CX - 12}" x2="${CX - 12}" y1="${y + 6}" y2="${y + RH - GAP - 6}"/>`);
          centre[b.name] = y + (RH - GAP) / 2;
          y += RH;
        }
        // supplies and FEDs sit beside the boxes they serve
        for (const [kind, x, w, relation] of [['lv_supply', SX, SW, 'powered_by'], ['fed', FX, FW, 'read_out_by']]) {
          const names = [...new Set(boxes.flatMap((b) => rel(b, relation)))];
          for (const n of names) {
            const served = boxes.filter((b) => rel(b, relation).includes(n)).map((b) => centre[b.name]);
            const cy = served.reduce((a, v) => a + v, 0) / served.length;
            body += node(by[n], x, cy - (RH - GAP) / 2, w, RH - GAP);
            for (const sy of served) {
              wires += kind === 'lv_supply' ? `<path class="wire" d="M${x + w},${cy} C${x + w + 35},${cy} ${BX - 35},${sy} ${BX},${sy}"/>`
                : `<path class="wire" d="M${BX + BW},${sy} C${BX + BW + 35},${sy} ${x - 35},${cy} ${x},${cy}"/>`;
            }
          }
        }
        body += `<line class="grid" x1="${SX}" x2="${W - 16}" y1="${y + 2}" y2="${y + 2}"/>`;
        y += 14;
        void top;
      }
    }
  }
  const head = `<text x="${SX}" y="${y + 8}">low-voltage supplies (power the boxes)</text>
    <text x="${BX + BW / 2}" y="${y + 8}" text-anchor="middle">readout boxes and their channels</text>
    <text x="${FX + FW}" y="${y + 8}" text-anchor="end">FEDs (read the boxes out)</text>`;
  return `<svg viewBox="0 0 ${W} ${y + 18}" width="${W}" height="${y + 18}" role="img" aria-label="detector map">${wires}${body}${head}</svg>`;
}
function mapHeader(d) {
  const top = d.elements.filter((e) => e.kind === 'experiment' || e.kind === 'detector');
  const bits = top.map((e) => `<b>${elLink(e.name)}</b> <span class="muted">${e.kind}</span>` +
    Object.entries(e.states).map(([k, v]) => ` · ${k.replace(/_/g, ' ')}: <b>${esc(v.value)}</b> since ${tm(v.since)}`).join('') +
    d.open_issues.filter((i) => i.element === e.name).map((i) => ` · <a href="#/incident/${i.id}">open issue #${i.id}</a> (${i.status})`).join(''));
  return `<p>${bits.join('<br>')}</p>`;
}

/* --------------------------------------------------------------- tables */
const ER_POS = { element: [20, 20], element_relation: [20, 150], part_ref: [20, 290], entry: [290, 20], incident: [290, 330],
  link: [570, 20], incident_entry: [570, 250], precedent: [570, 380], certification: [570, 580], run: [850, 20], fill: [850, 180], beam_mode: [850, 300], query_log: [850, 400], meta: [850, 540] };
function erDiagram(tables) {
  const BW = 210, HH = 26, RH = 16;
  const idx = Object.fromEntries(tables.map((t) => [t.name, t]));
  const rowY = (t, i) => ER_POS[t][1] + HH + RH * i + 11;
  let boxes = '', edges = '';
  for (const t of tables) {
    const [x, y] = ER_POS[t.name], h = HH + RH * t.columns.length + 6;
    boxes += `<g class="hit" data-scroll="t-${t.name}" data-tip="${esc(t.purpose)}"><rect class="node" x="${x}" y="${y}" width="${BW}" height="${h}" rx="6"/>
      <text class="title" x="${x + 10}" y="${y + 17}">${t.name}</text><text x="${x + BW - 10}" y="${y + 17}" text-anchor="end">${t.count} rows</text>
      <line class="axis" x1="${x}" x2="${x + BW}" y1="${y + HH - 2}" y2="${y + HH - 2}"/>
      ${t.columns.map(([name, , ref], i) => `<text x="${x + 10}" y="${rowY(t.name, i) + 4}"${name === 'id' ? ' class="title"' : ''}>${name}${ref ? ' → ' + ref : ''}</text>`).join('')}</g>`;
    t.columns.forEach(([, , ref], i) => {
      if (!ref) return;
      const [tt, tc] = ref.split('.');
      if (tt === t.name) return;                       // a row pointing at its own table: said in the text
      const [tx] = ER_POS[tt], y1 = rowY(t.name, i), y2 = rowY(tt, idx[tt].columns.findIndex((c) => c[0] === tc));
      let d;
      if (tx === x) d = `M${x},${y1} C${x - 22},${y1} ${x - 22},${y2} ${x},${y2}`;
      else if (tx < x) d = `M${x},${y1} C${x - 30},${y1} ${tx + BW + 30},${y2} ${tx + BW},${y2}`;
      else d = `M${x + BW},${y1} C${x + BW + 30},${y1} ${tx - 30},${y2} ${tx},${y2}`;
      const ex = tx === x ? x : tx < x ? tx + BW : tx;
      edges += `<path class="wire" d="${d}"/><circle class="wire-end" cx="${ex}" cy="${y2}" r="3.5"/>`;
    });
  }
  const H = Math.max(...tables.map((t) => ER_POS[t.name][1] + HH + RH * t.columns.length + 16));
  return `<svg viewBox="0 0 1080 ${H}" width="1080" height="${H}" role="img" aria-label="the tables of the Record and how they point to each other">${boxes}${edges}</svg>`;
}
const TIME_COL = /(_at|^t_start|^t_end|^as_of)$/;
function rawTable(t, highlight) {
  if (!t.rows.length) return '<p class="muted">No rows at this time.</p>';
  const cell = (col, v) => {
    if (v == null) return '<span class="unknown">empty</span>';
    if (TIME_COL.test(col)) return `<span data-tip="${fmtFull(v)}, stored as ${v} (seconds since 1970)">${fmt(v)}</span>`;
    const str = String(v);
    return str.length > 46 ? `<span data-tip="${esc(str)}">${esc(str.slice(0, 44))}…</span>` : esc(str);
  };
  return `<div class="tablewrap"><table class="raw"><tr>${t.columns.map((c) => `<th class="${highlight && highlight.includes(c) ? 'hl' : ''}">${c}</th>`).join('')}</tr>
    ${t.rows.map((r) => `<tr>${r.map((v, i) => `<td class="${highlight && highlight.includes(t.columns[i]) ? 'hl' : ''}">${cell(t.columns[i], v)}</td>`).join('')}</tr>`).join('')}</table></div>`;
}

const ROLE_CLASS = { symptom: 'c1', downtime: 'c2', action: 'c3', certification: 'c4', cause: 'c5', closing_note: 'c5', evidence: 'c7' };
const ROLE_LABEL = { symptom: 'symptom', downtime: 'downtime', action: 'action taken', certification: 'certification', cause: 'cause or closing note', evidence: 'evidence linked by an expert' };
function knowledgeChart(inc, entries, width, steps, notes) {
  // Time is drawn relative to the start of the incident on a compressed scale, so minutes
  // and weeks fit on one axis: equal distance means ten times longer.
  const f = (dt) => Math.sign(dt) * Math.log10(1 + Math.abs(dt) / 60);
  const L = 118, R = 20, W = Math.max(520, width), LABELS = 128;
  const ys = 22, yTop = (steps ? ys + 22 : 14) + LABELS, yBot = yTop + 110, H = yBot + 50;
  const all = entries.flatMap((e) => [e.t_start - inc.t_start, e.known_at - inc.t_start]).concat(S.replay ? [S.asOf - inc.t_start, 0] : [0])
    .concat(steps ? steps.map((t) => t - inc.t_start) : []);
  const lo = f(Math.min(...all)) - 0.2, hi = f(Math.max(...all)) + 0.2;
  const X = (dt) => L + ((f(dt) - lo) / (hi - lo)) * (W - L - R);
  const top = steps ? ys - 12 : yTop - LABELS;
  let s = `<text x="${L - 8}" y="${yTop + 4}" text-anchor="end">Happened</text><text x="${L - 8}" y="${yBot + 4}" text-anchor="end">Known</text>
    <line class="axis" x1="${L}" x2="${W - R}" y1="${yTop}" y2="${yTop}"/><line class="axis" x1="${L}" x2="${W - R}" y1="${yBot}" y2="${yBot}"/>`;
  const marks = [[-7 * 86400, '1 wk before'], [-86400, '1 d before'], [-6 * 3600, '6 h before'], [-3600, '1 h before'], [-600, '10 min before'], [0, 'start'],
    [600, '+10 min'], [3600, '+1 h'], [6 * 3600, '+6 h'], [86400, '+1 d'], [7 * 86400, '+1 wk'], [14 * 86400, '+2 wk'], [28 * 86400, '+4 wk']];
  for (const [dt, label] of marks) {
    if (f(dt) < lo || f(dt) > hi) continue;
    s += `<line class="grid" x1="${X(dt)}" x2="${X(dt)}" y1="${top}" y2="${yBot + 14}"/><text x="${X(dt)}" y="${yBot + 30}" text-anchor="middle">${label}</text>`;
  }
  if (S.replay) {
    const xn = X(S.asOf - inc.t_start);
    s += `<rect class="future" x="${xn}" y="${top}" width="${Math.max(0, W - R - xn)}" height="${yBot + 14 - top}"/>
      <line class="asof" x1="${xn}" x2="${xn}" y1="${top}" y2="${yBot + 14}"/>`;
  }
  if (steps) {
    s += `<text x="${L - 8}" y="${ys + 4}" text-anchor="end">Steps</text><line class="axis" x1="${L}" x2="${W - R}" y1="${ys}" y2="${ys}"/>`;
    steps.forEach((t, k) => {
      const here = t === S.asOf, past = t <= S.asOf;
      const said = notes && notes[String(t)] ? notes[String(t)].join('\n') : '';
      const tip = past ? `step ${k + 1}: ${said || 'something was learned'}` : `step ${k + 1}, later: click to go there`;
      s += `<circle class="hit step${here ? ' here' : past ? ' past' : ''}" cx="${X(t - inc.t_start)}" cy="${ys}" r="${here ? 8 : 5.5}" data-asof="${t}" data-tip="${esc(tip)}"/>`;
    });
  }
  // what happened, written on the Happened line: one label per entry, repeated ones grouped
  const sorted = [...entries].sort((a, b) => a.t_start - b.t_start || a.id - b.id);
  const lastStep = steps ? [...steps].reverse().find((t) => t <= S.asOf) : null;
  const isFresh = (e) => !!S.replay && lastStep != null && e.known_at === lastStep;
  const groups = [];
  for (const e of sorted) {
    const x = X(e.t_start - inc.t_start), g = groups[groups.length - 1];
    if (g && g.text === e.short && x - g.lastX < 45) { g.n += 1; g.lastX = x; g.fresh = g.fresh || isFresh(e); continue; }
    groups.push({ x, lastX: x, text: e.short || e.type, n: 1, fresh: isFresh(e) });
  }
  let lastX = -1e9;
  for (const g of groups) {
    const lx = Math.max(g.x, lastX + 24);         // keep rotated labels from overlapping (24 px apart = 15 px between lines)
    lastX = lx;
    if (lx - g.x > 1) s += `<line class="leader" x1="${g.x}" y1="${yTop - 6}" x2="${lx}" y2="${yTop - 12}"/>`;
    s += `<text class="hlabel${g.fresh ? ' fresh' : ''}" transform="translate(${lx + 2},${yTop - 12}) rotate(-38)">${esc(g.text)}${g.n > 1 ? ` ×${g.n}` : ''}</text>`;
  }
  for (const e of entries) {
    const cls = e.role ? (ROLE_CLASS[e.role] || 'c1') : 'c0', a = X(e.t_start - inc.t_start), b = X(e.known_at - inc.t_start);
    const tip = `${e.role || 'symptom, not yet linked to an incident'}: ${describe(e)}\nhappened ${fmt(e.t_start)}\nknown ${fmt(e.known_at)} (${dur(e.known_at - e.t_start)} later)`;
    s += `<g class="hit ${cls}" data-go="#/entry/${e.id}" data-tip="${esc(tip)}"><line x1="${a}" y1="${yTop}" x2="${b}" y2="${yBot}" stroke-width="2" opacity=".75"/>
      <circle cx="${a}" cy="${yTop}" r="5" stroke="var(--surface)" stroke-width="2"/><circle cx="${b}" cy="${yBot}" r="5" stroke="var(--surface)" stroke-width="2"/></g>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="when each entry happened and when it became known">${s}</svg>`;
}

/* ------------------------------------------------------------------------- pages */
const PAGES = {};
const NAV = [
  ['1', 'detector', 'The detector'],
  ['2', 'built', 'How the Record is built', [['built', 'Overview'], ['interfaces', 'Interfaces of unbuilt parts']], true],
  ['3', 'tables', 'What is in the Record', [['tables', 'Tables'], ['record', 'Entries'], ['incidents', 'Incidents'], ['timeline', 'Timeline']]],
  ['4', 'scenarios', 'Scenarios in this demo', null, true],
  ['5', 'replay', 'Replay'],
  ['6', 'agent', 'The agent'],
];
const ALIAS = { entry: 'record', incident: 'incidents' };
function drawNav(current) {
  const cur = ALIAS[current] || current;
  $('#nav').innerHTML = NAV.map(([n, key, label, subs, demo]) => {
    const on = cur === key || (subs && subs.some(([k]) => k === cur));
    return `<a href="#/${key}" class="navtop${on && !subs ? ' on' : ''}${demo ? ' demo' : ''}" ${demo ? 'title="Demo explainer: not part of the production Record browser"' : ''}><span class="n">${n}</span>${label}</a>` +
      (subs ? `<div class="subs">${subs.map(([k, l]) => `<a href="#/${k}" class="${cur === k ? 'on' : ''}">${l}</a>`).join('')}</div>` : '');
  }).join('') + '<div class="navfoot"><span class="demo-key"></span> demo explainer, not part of the production Record browser<br><br><a href="#/api">For developers: read API</a></div>';
}

const EXPLAINER = (what) => `<div class="explainer"><b>Demo explainer, not part of the production Record browser.</b> ${what}</div>`;
/* 1. the detector ------------------------------------------------------------------ */
PAGES.detector = async () => {
  const d = await api('map');
  const m = S.meta, n = (k) => d.elements.filter((e) => e.kind === k).length;
  const html = `<h1>The detector</h1>
  <dl class="facts card about"><dt>This Record covers</dt><dd><b>${tm(m.t0)} to ${tm(m.t1)}</b> UTC (${dur(m.t1 - m.t0)})</dd>
    <dt>Generated with</dt><dd>preset <b>${esc(m.preset)}</b>, seed ${esc(m.seed)}</dd>
    <dt>File</dt><dd class="mono">${esc(m.path)} (${m.size_mb} MB, opened read-only) <button data-recfile>load a different Record</button></dd></dl>
  <p class="lead">A synthetic, HCAL-like device: ${n('subdetector')} subdetectors, ${n('readout_box')} readout boxes with ${n('channel')} channels, ${n('lv_supply')} low-voltage supplies and ${n('fed')} FEDs. Everything in the Record is about one of these parts.</p>
  <div class="note"><b>Two things to know first.</b> All of this is invented: real detector names, no real events. And the Record you are browsing was written <b>directly by a generator</b>; none of the software that would build it from real sources runs here. <a href="#/built">How the Record is built</a> explains both.</div>
  <div id="map"></div>
  <div class="key"><span>Click a part to see its readings over time.</span><span><i style="background:var(--critical)"></i>red outline: a state other than "on" or "ok"</span><span><i style="background:var(--critical);height:9px;width:9px"></i>channel flagged hot</span></div>
  ${S.replay ? `<p>${mapHeader(d)}</p>` : ''}
  <h2>Why the connections matter</h2>
  <p>A fault in a shared part shows up in everything it serves. If a supply trips, every box it powers goes dead. If a FED loses sync, every box it reads stops sending data. So two records can be related because they are about the same part, or because their parts share a supply or a FED.</p>
  <h2>The parts</h2>
  <div class="tablewrap"><table><tr><th>Kind</th><th class="num">How many</th><th>What it is</th></tr>
    <tr><td>subdetector</td><td class="num">${n('subdetector')}</td><td>A section of the calorimeter (HB, HE, HF, HO). Certification is given per subdetector.</td></tr>
    <tr><td>readout box</td><td class="num">${n('readout_box')}</td><td>On-detector electronics for a group of channels. Voltage and temperature are measured per box; the Record keeps their status changes, the full series stay in the source archive.</td></tr>
    <tr><td>channel</td><td class="num">${n('channel')}</td><td>One readout channel. Only flagged when it misbehaves.</td></tr>
    <tr><td>low-voltage supply</td><td class="num">${n('lv_supply')}</td><td>Powers one or more boxes. Has a state: on, off or tripped.</td></tr>
    <tr><td>FED</td><td class="num">${n('fed')}</td><td>Back-end board that reads out one or more boxes.</td></tr></table></div>`;
  return { html, mount() { $('#map').innerHTML = mapSvg(d, $('#map').clientWidth); } };
};

/* 2. how the Record is built --------------------------------------------------------- */
PAGES.built = async () => {
  const d = await api('built');
  const ex = d.examples, src = d.source, arc = d.archive;
  const cad = d.config.raw_cadence_s, every = cad >= 60 ? `${cad / 60} minute${cad === 60 ? '' : 's'}` : `${cad} s`;
  const box = (name, what, state) => (state === 'off' && name !== 'Existing systems' ? `<a class="box ${state}" href="#/interfaces"><b>${name}</b>${what}</a>` : `<div class="box ${state}"><b>${name}</b>${what}</div>`);
  const code = (key, label) => (src[key] ? ` <a class="code" href="${src[key].href}" target="_blank" rel="noopener">${label || 'code'}: ${esc(src[key].file)}:${src[key].line}</a>` : '');
  const entryCell = (e) => (e ? `<span class="mono small">entry ${entryLink(e.id)} · ${esc(e.source)}/${esc(e.type)} · ${esc(e.element)}<br>${esc(JSON.stringify(e.payload))}</span>` : 'none in this Record');
  const linkCell = (x) => (x ? `<span class="mono small">link ${x.link.id} · ${x.link.link_type} · ${esc(x.link.relation)} · ${x.link.status}</span><br>
      <span class="small">from entry ${entryLink(x.src.id)}: ${esc(describe(x.src))}<br>to entry ${entryLink(x.dst.id)}: ${esc(describe(x.dst))}<br>reason: "${esc(x.link.rationale)}"</span>` : 'none in this Record');
  const inc = d.incident_example;
  const row = (what, demo, example, feed) => `<tr><td>${what}</td><td>${demo}</td><td class="what">${example}</td><td>${feed}</td></tr>`;
  const head = '<tr><th>What</th><th>What the demo does</th><th>Example from this Record</th><th>What the feed would do instead</th></tr>';
  const html = `${EXPLAINER('Most of this page is written by hand to describe this demo; only the examples are read from the loaded Record, so the rest can drift from it.')}
  <h1>How the Record is built</h1>
  <div class="note"><b>The message of this page.</b>
    <ol><li>On a real detector, a chain of software called the feed builds the Record from existing systems. <b>That chain does not exist here.</b></li>
    <li>A <b>generator</b> stands in for all of it: it invents a detector history and writes finished entries, links and incidents straight into the Record.</li>
    <li>So the Record's structure, its rules and everything that reads it are real. Its <b>contents</b>, and <b>every choice the feed would have to make</b>, are the generator's.</li></ol></div>

  <div class="pathlabel">As designed, for real records</div>
  <div class="flow">${box('Existing systems', 'controls, data quality, logbook, certification', 'off')}<span class="arrow">&#8594;</span>
    ${box('Adapters', 'read, map to parts', 'off')}<span class="arrow">&#8594;</span>${box('Anonymizer', 'names to roles', 'off')}<span class="arrow">&#8594;</span>
    ${box('Summarizer, sparsifier', 'shorten text, reduce readings', 'off')}<span class="arrow">&#8594;</span>${box('Aggregator', 'writes entries', 'real')}<span class="arrow">&#8594;</span>
    <a class="box real" href="#/tables"><b>The Record</b>${d.counts.entry} entries</a></div>
  <div class="pathlabel">In this demo</div>
  <div class="flow"><div class="box demo" style="flex:4 1 560px"><b>Generator</b>invents a calendar, plants fault situations, writes everything</div><span class="arrow">&#8594;</span>
    ${box('Aggregator', 'the same code', 'real')}<span class="arrow">&#8594;</span><a class="box real" href="#/tables"><b>The Record</b>the same database</a></div>
  <div class="flow"><div class="box demo" style="flex:4 1 560px"><b>Generator</b>also writes the full voltage and temperature series into a simulated control-system archive: a source system, not the Record${arc ? ` (${arc.channels} series, ${(arc.samples / 1e3).toFixed(0)}k samples)` : ''}</div><span class="arrow">&#8594;</span>
    ${box('Adapter', 'fetches a series on demand', 'real')}<span class="arrow">&#8594;</span><a class="box real" href="#/timeline"><b>Timeline</b>draws it; nothing is copied</a></div>
  <div class="key"><span><i class="k-off"></i>dashed: not built; click for its interface</span><span><i class="k-real"></i>blue: runs here</span><span><i class="k-demo"></i>violet: the generator, demo only</span></div>

  <h2>How time series are treated</h2>
  <p><b>The Record keeps what changed, not the samples.</b> The full series stays in the source; the Record stores one entry each time a reading changes status, with a pointer back.</p>
  ${Object.keys(d.status_rules || {}).length ? `<p><b>The status rule</b> used for this Record${code('status_rule', 'rule')}:</p><ul class="rules">${Object.entries(d.status_rules || {}).map(([q, r]) => `<li><b>${esc(q.replace('_', ' '))}</b>: ${esc(r)}</li>`).join('')}</ul>` : ''}
  <div id="ts-demo"></div>
  <div class="genbox">
  <h2>What the generator does in place of the feed</h2>
  <p>It first lays out a calendar of fills and runs and decides where each <a href="#/scenarios">planted situation</a> goes${code('calendar')}. Then it writes the Record through the aggregator${code('write')}. Each row below shows one thing it writes, with a real example.</p>
  <h3>It writes the entries the feed would have produced</h3>
  <div class="tablewrap"><table>${head}
    ${row('<b>A voltage reading</b>', `Invents the full series, a sample every ${every}, and writes it to the simulated archive${code('voltage')}. Applies a fixed rule to it and writes an entry each time the status changes${code('status_rule', 'rule')}.`, entryCell(ex.voltage),
      'The series is already in the control-system archive. The <b>sparsifier</b> applies a status rule owned by the subsystem and writes the changes, each with a pointer into the archive.')}
    ${row('<b>Data quality of a run</b>', `Sets five numbers per run and box from the planted faults, plus 1% noise, and writes them to a simulated data-quality archive. Writes an entry each time a box's quality status changes, against a reference per subdetector${code('quality')}.`, entryCell(ex.quality),
      'The <b>sparsifier</b> extracts numbers from data-quality histograms in the source and records quality status changes, with a pointer.')}
    ${row('<b>Runs, fills, beam modes</b>', `Writes them to calendar tables, not as entries. Only a run stopped by a fault, and a configure attempt that was not routine, become entries${code('calendar_write')}.`, d.calendar ? `${d.calendar.runs} runs, ${d.calendar.fills} fills in the calendar` : '',
      'A run-control <b>adapter</b> fills the calendar from run control and the LHC.')}
    ${row('<b>Certification</b>', `Records when each run was certified per subdetector. Writes an entry only for a bad lumisection range; good is inferred${code('certification')}.`, d.calendar ? `${d.calendar.certified} run-and-subdetector certifications` : '',
      'The certification <b>adapter</b> reads the certification database.')}
    ${row('<b>A logbook note</b>', `Picks one of two or three hand-written sentences per situation and fills in names of parts. There are never people's names.${code('note', 'templates')}`, entryCell(ex.note),
      'The <b>anonymizer</b> replaces names with roles; the <b>summarizer</b> shortens long threads. Both use local language models.')}
  </table></div>
  <h3>It also writes what experts and software would add on top</h3>
  <div class="tablewrap"><table>${head}
    ${row('<b>A direct link</b><br><span class="small muted">same part or time; context, not cause</span>', `Links each downtime row to the run it stopped.${code('direct_link')}`, linkCell(d.links.direct),
      'The <b>aggregator</b> builds them from shared identifiers and timestamps.')}
    ${row('<b>An indirect link</b><br><span class="small muted">an expert\'s reasoning</span>', `The fault script writes it as already confirmed, with one fixed sentence as the reason, at the moment the cause is recorded.${code('indirect_link')}`, linkCell(d.links.indirect),
      'Software <b>proposes</b> which observation supports which conclusion; an <b>expert</b> confirms, corrects or rejects each one.')}
    ${row('<b>Parts a record concerns</b><br><span class="small muted">beyond the one it was filed under</span>', `Names the other parts each entry and incident concerns, with a role and a time: the boxes a FED reads out, the supply behind a box, the box suspected and then confirmed as the cause${code('parts')}.`,
      d.part_example ? `${incLink(d.part_example.incident.id, d.part_example.incident.title)}<br><span class="small">${d.part_example.parts.map((r) => `${r.role}: ${esc(r.element)}, ${tm(r.known_at)}`).join('<br>')}</span>` : 'none',
      'The <b>summarizer</b> proposes which parts a note is about; <b>experts</b> confirm suspected and cause parts.')}
    ${row('<b>An incident</b><br><span class="small muted">entries grouped into one problem</span>', `Every planted fault gets a complete incident from its script: symptoms, action, recovery, usually a cause.${code('incident', 'one fault script')}`,
      inc ? `${incLink(inc.incident.id, inc.incident.title)}<br><span class="small">${inc.n_entries} entries, ${inc.n_links} expert links<br>recovery: ${esc(inc.incident.recovery_action || 'none')}<br>cause: ${esc(inc.incident.confirmed_cause || 'none')}</span>` : 'none in this Record',
      'For selected incidents, the team and the <b>experts</b> who handled them reconstruct the history. The rest are grouped automatically and unreviewed.')}
  </table></div>
  </div>

  <h2>Choices the generator makes on the feed's behalf</h2>
  <p>Each row is a real design decision that is <b>not settled</b>. The demo fixes it silently; this table is here so nobody mistakes it for decided. Details are in docs/DESIGN.md, section 7a.</p>
  <div class="tablewrap"><table><tr><th>Choice</th><th>In the demo</th><th>What it hides</th></tr>
    <tr><td><b>Which reading changes are recorded</b></td><td>A fixed rule: compared with the setpoint, low or high beyond a band, drifting beyond a slope, must hold 10 minutes</td><td>The thresholds are hand-picked. A change the rule misses is only in the archive, not in the Record; a change is recorded 10 minutes late</td></tr>
    <tr><td><b>Which quality changes are recorded</b></td><td>Five numbers per run and box, compared once per run with a reference per subdetector</td><td>Short problems are diluted in a run; position within a box is lost; the reference is updated by hand</td></tr>
    <tr><td><b>Certification</b></td><td>Only bad ranges stored; good inferred once certification is complete</td><td>Re-certification that withdraws a bad range would need a correction entry; not exercised here</td></tr>
    <tr><td><b>Plots</b></td><td>None</td><td>Intended: keep an incident's relevant plots, mostly logbook attachments</td></tr>
    <tr><td><b>When quality data arrive</b></td><td>Ten minutes after the run</td><td>Online plots are visible during a run</td></tr>
    <tr><td><b>The source archive</b></td><td>Evenly spaced samples, kept for ever, read instantly</td><td>Real archives store on change, may expire, and can be slow or unreachable</td></tr>
    <tr><td><b>Logbook text</b></td><td>One templated sentence</td><td>Real notes are long and irregular; matching is harder</td></tr>
    <tr><td><b>Which parts a record concerns</b></td><td>Named by the generator, which knows where it planted each fault</td><td>Must be read from free text and confirmed by experts; roles are a first guess at a vocabulary</td></tr>
    <tr><td><b>How late knowledge arrives</b></td><td>Fixed delays</td><td>Real delays vary; many causes are never written</td></tr>
    <tr><td><b>Complete incidents</b></td><td>Every fault has one</td><td>Only expert-reviewed incidents are this complete</td></tr>
    <tr><td><b>Language models</b></td><td>None used</td><td>The anonymizer and summarizer would use local ones</td></tr>
  </table></div>`;
  return { html, mount: () => tsIllustration(ex.voltage, d.config.raw_cadence_s) };
};
async function tsIllustration(e, cad) {
  const host = $('#ts-demo');
  if (!host || !e) return;
  const t0 = e.t_start - 2 * 3600, t1 = e.t_start + 8 * 3600;
  const [tl, rec] = await Promise.all([api('timeline', { element: e.element, t0, t1 }),
    api('entries', { element: e.element, type: e.type, t0, t1, limit: 50 })]);
  const panel = tl.panels.find((p) => p.type === 'lv_voltage');
  const cfg = { t0, t1, width: host.clientWidth, panels: [{ ...panel, label: `Fetched: ${e.element} low voltage, every sample, from the source archive`, series: panel.series.filter((x) => x.box === e.element) }],
    rows: [{ label: 'Stored', items: rec.entries.map((x) => ({ t0: x.t_start, shape: 'diamond', cls: x.payload.value === 'normal' ? 'mk' : 'mk crit', tip: `${fmt(x.t_start)}\n${x.payload.value} (recorded ${fmt(x.known_at)})`, go: `#/entry/${x.id}` })) }],
    aria: 'one voltage series from the archive, and the few entries the Record keeps for it' };
  const chart = buildChart(cfg);
  const samples = Math.round((t1 - t0) / cad);
  host.innerHTML = `<p class="small muted">One box's voltage over 10 hours: <b>${samples.toLocaleString()} samples fetched</b> from the source, <b>${rec.total} entries stored</b> in the Record.</p>` + chart.svg +
    `<p class="small"><b>Stored in the Record</b></p><div class="tablewrap"><table><tr><th>Status from</th><th>Recorded</th><th>Status</th><th>Reading</th><th>Pointer into the source</th></tr>${rec.entries.map((x) =>
      `<tr class="click" data-go="#/entry/${x.id}"><td class="t">${tm(x.t_start)}</td><td class="t">${tm(x.known_at)}</td><td><b>${esc(x.payload.value)}</b></td><td>${x.payload.reading} ${esc(x.payload.unit)}</td><td class="mono small">${esc(x.raw_ref)}</td></tr>`).join('')}</table></div>`;
}

/* 2b. interfaces of the parts not built ---------------------------------------------- */
const KIND_LABEL = { contract: 'contract', record: 'data it passes on', implementation: 'implementation', function: 'function' };
PAGES.interfaces = async () => {
  const d = await api('interfaces');
  const groups = [['feed', 'The feed: from existing systems into the Record'], ['aggregator', 'The aggregator'], ['orchestrator', 'The orchestrator: reading the Record to help a crew']];
  const fieldTable = (fs) => (fs.length ? `<table class="sig"><tr><th>Field</th><th>Type</th><th>Meaning</th></tr>${fs.map((f) => `<tr><td class="mono">${esc(f.name)}</td><td class="mono small">${esc(f.type)}</td><td class="small">${esc(f.note)}</td></tr>`).join('')}</table>` : '');
  const methodList = (ms, file) => (ms.length ? `<ul class="sigs">${ms.map((m) => `<li><a class="mono" href="/source/${file}#L${m.line}" target="_blank" rel="noopener">${esc(m.signature)}</a>${m.doc ? `<br><span class="small">${esc(m.doc)}</span>` : ''}</li>`).join('')}</ul>` : '');
  const card = (i) => {
    const impls = i.items.filter((x) => x.kind === 'implementation' && i.status !== 'built');
    const main = i.items.filter((x) => !(x.kind === 'implementation' && i.status !== 'built'));
    return `<div class="card iface" id="if-${i.file.replace(/\W/g, '-')}"><h3 style="margin-top:0">${esc(i.title)} <span class="ifstatus${i.status === 'built' ? ' built' : ''}">${i.status === 'built' ? 'built' : 'interface only'}</span>
      <a class="code" href="/source/${i.file}#L1" target="_blank" rel="noopener">${esc(i.file)}</a></h3>
      <p>${esc(i.role)}</p>
      ${i.example && i.example.input ? `<div class="io"><div><b>Takes</b><pre>${esc(i.example.input)}</pre></div><div><b>Gives</b><pre>${esc(i.example.output)}</pre></div></div>` : ''}
      ${i.produced ? `<p class="small"><b>An entry of the kind it would produce</b>, from this Record (written by the generator):</p><div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows([i.produced])}</table></div>` : ''}
      ${main.map((x) => `<h4>${esc(x.name)} <span class="muted small">${KIND_LABEL[x.kind]}</span></h4>${x.doc ? `<p class="small">${esc(x.doc)}</p>` : ''}${fieldTable(x.fields)}${methodList(x.methods, i.file)}`).join('')}
      ${impls.length ? `<h4>Implementations to write</h4><ul class="sigs">${impls.map((x) => `<li><a class="mono" href="/source/${i.file}#L${x.line}" target="_blank" rel="noopener">${esc(x.name)}</a> <span class="small">${esc(x.doc)}</span></li>`).join('')}</ul>` : ''}
    </div>`;
  };
  const html = `${EXPLAINER('Read from the code of this repository, not from the Record.')}
  <h1>Interfaces of the parts not built yet</h1>
  <p class="lead">Each part of the design that does not run yet exists as code that fixes its interface: what it takes, what it gives, and the calls it must answer. This page is read from that code, so it cannot drift from it. Every method raises "not implemented".</p>
  <div class="note">Where a part would produce entries, the card shows one real entry of that kind from this Record. Today the generator writes those entries itself; the interface says what a real part must produce instead.</div>
  ${groups.map(([g, title]) => `<h2>${title}</h2>${d.interfaces.filter((i) => i.group === g).map(card).join('')}`).join('')}
  <h2>The detector model</h2>
  <div class="card iface"><h3 style="margin-top:0">Detector model <span class="ifstatus">planned</span></h3>
    <p>Not yet written as code. The plan is in <span class="mono">docs/DETECTOR_PLAN.md</span>: one interface (the map at a time, the views, the parts, the channels a part covers, translating between views) with the toy detector and cmscoord behind it.</p></div>`;
  return { html };
};

/* 3. what is in the Record ----------------------------------------------------------- */
const TB = { incident: null };
PAGES.tables = async () => {
  const d = await api('tables', TB.incident ? { incident: TB.incident } : {});
  const w = d.walk;
  const html = `<h1>What is in the Record: the tables</h1>
  <p class="lead">The Record is one database with eight tables. A line in the diagram means "this column holds the id of a row in that table". Click a table for its columns and real rows.</p>
  <div class="tablewrap">${erDiagram(d.tables)}</div>
  <div class="note">An <b>element</b> is a part of the detector. An <b>entry</b> is one recorded thing about one element, with two times: when it happened and when the Record learned of it. A <b>link</b> connects two entries. An <b>incident</b> is a problem; <b>incident_entry</b> lists which entries belong to it and in what role. <b>element_relation</b> says which supply powers a box and which FED reads it.</div>
  <div class="note"><b>Several parts per record.</b> <span class="mono">part_ref</span> lists every part an entry or incident concerns, each with a role and its own time: an incident reported on HCAL can name a readout box as suspected six hours later, and the box and its supply as the cause six days later. Every entry has exactly one "filed" part, the one its source filed it under; <span class="mono">entry.element_id</span> keeps a copy of it. <b>fill</b>, <b>run</b> and <b>beam_mode</b> are the calendar; <b>certification</b> says when each run was certified.</div>
  <h2>One incident, followed through the tables</h2>
  ${w ? `<div class="filters"><label>Incident <select id="tb-inc">${d.incidents.map((i) => `<option value="${i.id}"${i.id === d.incident_id ? ' selected' : ''}>#${i.id} ${esc(i.title)}</option>`).join('')}</select></label> <a href="#/incident/${d.incident_id}">open its page</a></div>
  <h3>1. One row in <span class="mono">incident</span></h3>${rawTable(w.incident, ['id', 'element_id'])}
  <h3>1b. Rows in <span class="mono">part_ref</span> with incident_id = ${d.incident_id}</h3><p class="muted small">The parts it concerns, each with a role and its own time.</p>${rawTable(w.part_ref, ['incident_id', 'element_id'])}
  <h3>2. Rows in <span class="mono">incident_entry</span> with incident_id = ${d.incident_id}</h3><p class="muted small">Each attaches one entry and says what part it plays. First ${w.incident_entry.rows.length} shown.</p>${rawTable(w.incident_entry, ['incident_id', 'entry_id'])}
  <h3>3. The rows in <span class="mono">entry</span> those point to</h3><p class="muted small">Compare t_start with known_at to see how late each was learned.</p>${rawTable(w.entry, ['id', 'element_id'])}
  <h3>4. The rows in <span class="mono">element</span> those are about</h3>${rawTable(w.element, ['id', 'parent_id'])}
  <h3>5. Rows in <span class="mono">link</span> between those entries</h3>${rawTable(w.link, ['src_entry_id', 'dst_entry_id'])}`
    : '<p class="muted">No incident is on record at this moment.</p>'}
  <h2>Each table</h2>
  ${d.tables.map((t) => `<div class="card" id="t-${t.name}"><h3 style="margin-top:0"><span class="mono">${t.name}</span> <span class="muted">· ${t.count} rows</span></h3>
    <p>${esc(t.purpose)}</p>
    <div class="tablewrap"><table><tr><th>Column</th><th>Meaning</th><th>Points to</th></tr>${t.columns.map(([n, m, r]) => `<tr><td class="mono">${n}</td><td>${esc(m)}</td><td class="mono">${r}</td></tr>`).join('')}</table></div>
    <h3>Example rows</h3>${rawTable(t.sample)}</div>`).join('')}`;
  return { html, mount() {
    const sel = $('#tb-inc');
    if (sel) sel.addEventListener('change', () => { TB.incident = sel.value; render(); });
    document.querySelectorAll('[data-scroll]').forEach((g) => g.addEventListener('click', () => document.getElementById(g.dataset.scroll).scrollIntoView({ behavior: 'smooth', block: 'start' })));
  } };
};

const TREE = { closed: new Set() };
const RF = { cls: '', source: '', type: '', kind: '', element: '', below: false, q: '', order: 'oldest', offset: 0 };
PAGES.record = async () => {
  const o = await api('overview');
  const params = { limit: 100, offset: RF.offset, order: RF.order };
  if (RF.cls) params.class = RF.cls; if (RF.source) params.source = RF.source; if (RF.type) params.type = RF.type;
  if (RF.q) params.q = RF.q;
  if (RF.element) { params.element = RF.element; if (RF.below) params.below = 1; }
  const d = await api('entries', params);
  // class -> source -> type, with counts
  const tree = {};
  for (const [c, src, t, k, n] of o.entries_by_type) {
    tree[c] = tree[c] || { n: 0, sources: {} };
    tree[c].n += n;
    const sn = (tree[c].sources[src] = tree[c].sources[src] || { n: 0, types: [] });
    sn.n += n; sn.types.push([t, k, n]);
  }
  const on = (c, src, t) => RF.cls === c && (RF.source || '') === (src || '') && (RF.type || '') === (t || '');
  // a branch is open unless it was collapsed; clicking the selected branch again collapses it
  const node = (label, n, filter, level, active, key, extra = '') => `<div class="tn l${level}${active ? ' on' : ''}" data-pick='${JSON.stringify(filter)}'${key ? ` data-key="${key}"` : ''}>${key ? `<span class="chev">${TREE.closed.has(key) ? '&#9656;' : '&#9662;'}</span>` : ''}${label}<span class="tc">${n}</span>${extra}</div>`;
  const treeHtml = node('All entries', o.n_entries, {}, 0, !RF.cls && !RF.source && !RF.type) + ['MS', 'QA', 'HI'].filter((c) => tree[c]).map((c) => {
    const ck = `c:${c}`;
    return node(`${clsTag(c)} ${CLASS_NAME[c]}`, tree[c].n, { cls: c }, 1, on(c), ck) + (TREE.closed.has(ck) ? '' : Object.entries(tree[c].sources).sort((a, b) => b[1].n - a[1].n).map(([src, sn]) => {
      const sk = `s:${c}/${src}`;
      return node(esc(src), sn.n, { cls: c, source: src }, 2, on(c, src), sk) + (TREE.closed.has(sk) ? '' : sn.types.sort((a, b) => b[2] - a[2]).map(([t, k, n]) =>
        node(esc(t), n, { cls: c, source: src, type: t }, 3, on(c, src, t), null, `<span class="tk">${k}</span>`)).join(''));
    }).join(''));
  }).join('');
  const html = `<h1>What is in the Record: entries</h1>
  <p class="lead">Every event, status change, note and flag is one entry. Pick a branch on the left to narrow the list; click a row for the full entry.</p>
  <div class="split"><aside class="tree-panel">
    <div class="small muted">Class, then source, then type. ${o.entries_by_type.length} types.</div>${treeHtml}
    <p class="small muted">Classes: ${clsTag('MS')} readings and events from online systems, ${clsTag('QA')} data-quality results, ${clsTag('HI')} what people wrote or decided.</p></aside>
  <div class="split-main">
  <div class="filters">
    <label>Element <select data-rf="element"><option value="">all</option>${S.elements.map((e) => `<option${RF.element === e.name ? ' selected' : ''}>${esc(e.name)}</option>`).join('')}</select></label>
    <label><input type="checkbox" data-rf="below"${RF.below ? ' checked' : ''}> and everything below it</label>
    <label>Text <input type="text" data-rf="q" value="${esc(RF.q)}" placeholder="search the content"></label>
    <label>Order <select data-rf="order"><option value="oldest"${RF.order === 'oldest' ? ' selected' : ''}>oldest first</option><option value="newest"${RF.order === 'newest' ? ' selected' : ''}>newest first</option></select></label>
    <button data-rf-clear>Clear</button>
  </div>
  <div class="pager"><b>${d.total}</b> entries match. Showing ${d.total ? RF.offset + 1 : 0} to ${RF.offset + d.entries.length}.
    <button data-rf-page="-100"${RF.offset ? '' : ' disabled'}>&#9664; previous</button><button data-rf-page="100"${RF.offset + 100 < d.total ? '' : ' disabled'}>next &#9654;</button></div>
  <div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows(d.entries)}</table></div></div></div>`;
  return { html, mount() {
    document.querySelectorAll('[data-rf]').forEach((el) => el.addEventListener('change', () => { RF[el.dataset.rf] = el.type === 'checkbox' ? el.checked : el.value; RF.offset = 0; render(); }));
    $('[data-rf-clear]').addEventListener('click', () => { Object.assign(RF, { cls: '', source: '', type: '', element: '', below: false, q: '', offset: 0 }); render(); });
    document.querySelectorAll('[data-rf-page]').forEach((b) => b.addEventListener('click', () => { RF.offset = Math.max(0, RF.offset + (+b.dataset.rfPage)); render(); }));
    document.querySelectorAll('[data-pick]').forEach((r) => r.addEventListener('click', (ev) => {
      const key = r.dataset.key;
      if (key && (r.classList.contains('on') || ev.target.closest('.chev'))) {       // second click, or the arrow: open or close
        if (TREE.closed.has(key)) TREE.closed.delete(key); else TREE.closed.add(key);
        if (ev.target.closest('.chev') && !r.classList.contains('on')) { render(); return; }
      } else if (key) TREE.closed.delete(key);
      Object.assign(RF, { cls: '', source: '', type: '', offset: 0 }, JSON.parse(r.dataset.pick)); render();
    }));
  } };
};

PAGES.entry = async (parts) => {
  const d = await api('entry', { id: parts[1] });
  const e = d.entry;
  const html = `<h1>Entry ${e.id}</h1><p class="lead">${esc(describe(e))}</p>
  <div class="cols"><div class="card"><dl class="facts">
    <dt>Class</dt><dd>${e.record_class}</dd><dt>Source / type</dt><dd>${esc(e.source)} / ${esc(e.type)}</dd><dt>Kind</dt><dd>${e.kind}</dd>
    <dt>Element</dt><dd>${d.element_path.map(elLink).join(' &lsaquo; ')}</dd>
    <dt>Happened</dt><dd>${tm(e.t_start)}${e.t_end ? ' to ' + fmt(e.t_end) : ''}</dd>
    <dt>Known to the Record</dt><dd>${tm(e.known_at)} <span class="muted">(${dur(e.known_at - e.t_start)} after it started)</span></dd>
    <dt>Written by</dt><dd class="mono">${esc(e.producer)} ${esc(e.producer_version)}</dd>
    <dt>Source pointer</dt><dd class="mono">${esc(e.raw_ref)}</dd>
    <dt>Review status</dt><dd>${e.review_status}</dd>
    <dt>Corrects</dt><dd>${e.supersedes ? entryLink(e.supersedes) : 'nothing'}</dd>
    <dt>Corrected by</dt><dd>${d.superseded_by ? entryLink(d.superseded_by) : 'nothing'}</dd>
  </dl></div><div class="card"><b>Content (payload)</b><pre>${esc(JSON.stringify(e.payload, null, 2))}</pre></div></div>
  <h2>Parts this entry concerns</h2>
  <p class="muted small">"filed" is the part the source filed it under; the others were added with their own times.</p>
  ${partsTable(d.parts)}
  <h2>Incidents this entry belongs to</h2>
  ${d.incidents.length ? '<ul>' + d.incidents.map((i) => `<li>${incLink(i.id, i.title)} as <b>${esc(i.role)}</b></li>`).join('') + '</ul>' : '<p class="muted">None.</p>'}
  <h2>Links</h2>
  ${d.links.length ? `<div class="tablewrap"><table><tr><th>Link</th><th>Other entry</th><th>What it is</th><th>Reason given</th><th>Known</th></tr>${d.links.map((l) =>
    `<tr><td>${l.link_type}<br>${l.direction === 'out' ? 'this ' + esc(l.relation) + ' &#8594;' : '&#8592; ' + esc(l.relation) + ' this'}</td>
     <td>${entryLink(l.other.id)}</td><td class="what">${esc(describe(l.other))}</td><td class="what">${esc(l.rationale)}</td><td class="t">${tm(l.known_at)}</td></tr>`).join('')}</table></div>` : '<p class="muted">None.</p>'}`;
  return { html };
};

PAGES.incidents = async () => {
  const [d, o] = await Promise.all([api('incidents'), api('overview')]);
  const m = S.meta;
  const rows = [
    { label: 'Stable beams', items: o.beam.filter((b) => b.mode === 'STABLE BEAMS').map((b) => ({ t0: b.t0, t1: b.t1, cls: 'beam', tip: `Stable beams ${fmt(b.t0)} to ${fmt(b.t1)}` })) },
    { label: 'Technical stop', items: o.beam.filter((b) => b.mode === 'TECHNICAL STOP').map((b) => ({ t0: b.t0, t1: b.t1, cls: 'beam', tip: `Technical stop ${fmt(b.t0)} to ${fmt(b.t1)}` })) },
    { label: 'Downtime', items: o.downtime.map((e) => ({ t0: e.t_start, t1: e.t_end, cls: 'down', tip: describe(e), go: `#/entry/${e.id}` })) },
    { label: 'Incidents', items: d.incidents.map((i) => ({ t0: i.t_start, shape: 'diamond', cls: 'mk', tip: `#${i.id} ${i.title} (${i.status})`, go: `#/incident/${i.id}` })) },
  ];
  const html = `<h1>What is in the Record: incidents</h1>
  <p class="lead">An incident groups the entries that belong to one problem and keeps three labels apart: what restored running, the confirmed cause, and whether the data were usable.</p>
  <div id="cal"></div>
  <div class="tablewrap"><table><tr><th>#</th><th>Started</th><th>Status</th><th>Element</th><th>Title</th><th>Recovery action</th><th>Confirmed cause</th><th>Certification</th><th></th></tr>
  ${d.incidents.map((i) => `<tr class="click" data-go="#/incident/${i.id}"><td class="num">${i.id}</td><td class="t">${tm(i.t_start)}</td><td>${statusCell(i.status)}</td><td>${esc(i.element)}</td><td>${esc(i.title)}</td>
    <td class="what">${i.recovery_action ? esc(i.recovery_action) : empty()}</td><td class="what">${i.confirmed_cause ? esc(i.confirmed_cause) : empty()}</td><td>${i.certification ? esc(i.certification) : empty()}</td>
    <td><button data-replay="${i.id}">Replay</button></td></tr>`).join('')}
  </table></div>${d.incidents.length ? '' : '<p class="muted">No incident is on record at this moment.</p>'}
  <p class="muted small">Status: open, then mitigated once a recovery is recorded, then closed when a cause is confirmed, or unresolved if none was found.</p>`;
  return { html, mount() {
    const host = $('#cal');
    const cfg = { t0: m.t0, t1: m.t1, width: host.clientWidth, rows, vlines: S.replay ? [{ t: S.asOf, cls: 'asof' }] : [], aria: 'calendar of fills, downtime and incidents' };
    const chart = buildChart(cfg);
    host.innerHTML = chart.svg;
    wireChart(host, chart, cfg, {});
  } };
};

PAGES.incident = async (parts) => {
  const d = await api('incident', { id: parts[1] });
  const i = d.incident;
  const roles = [...new Set(d.entries.map((e) => (e.role === 'closing_note' ? 'cause' : e.role)))];
  const expert = d.links.filter((l) => l.link_type === 'indirect');
  const html = `<h1>Incident #${i.id}: ${esc(i.title)}</h1>
  <div class="card"><dl class="facts">
    <dt>Status</dt><dd>${statusCell(i.status)}</dd><dt>Element</dt><dd>${elLink(i.element)}</dd>
    <dt>Started</dt><dd>${tm(i.t_start)}</dd>
    <dt>Ended</dt><dd>${i.t_end ? fmt(i.t_end) + ` <span class="muted">(${dur(i.t_end - i.t_start)})</span>` : empty()}</dd>
    <dt>Recovery action</dt><dd>${i.recovery_action ? esc(i.recovery_action) : empty()}</dd>
    <dt>Confirmed cause</dt><dd>${i.confirmed_cause ? esc(i.confirmed_cause) : empty()}</dd>
    <dt>Certification</dt><dd>${i.certification ? esc(i.certification) : empty()}</dd>
  </dl></div>
  <div class="filters">${S.replay && S.replay.id === i.id ? '<a href="#/replay">Back to the replay</a>' : `<button class="primary" data-replay="${i.id}">Replay this incident</button> <span class="muted small">step through how the Record learned about it</span>`}
    · <a href="#/timeline/${encodeURIComponent(i.element)}">Timeline of ${esc(i.element)}</a></div>
  <h2>Parts this incident concerns</h2>
  <p class="muted small">Where it was reported, what it affected, and where the fault is suspected or confirmed to be, each with when the Record learned it.</p>
  ${partsTable(d.parts)}
  <h2>When each piece happened, and when the Record learned of it</h2>
  <p class="muted small">Each entry is drawn twice: when it happened (top) and when it became known (bottom). A vertical line was known at once; a long slanted line was written much later. The scale is compressed: each step to the right is about ten times longer.</p>
  <div class="key">${roles.map((r) => `<span><i class="${ROLE_CLASS[r]}"></i>${ROLE_LABEL[r] || r}</span>`).join('')}</div>
  <div id="know"></div>
  <h2>Entries attached (${d.entries.length})</h2>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}<th>Delay</th></tr>${d.entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}"><td>${esc(e.role)}</td>
    <td class="t">${tm(e.t_start)}</td><td class="t">${tm(e.known_at)}</td><td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td><td class="what">${esc(describe(e))}</td><td class="t">${dur(e.known_at - e.t_start)}</td></tr>`).join('')}</table></div>
  <h2>Expert reasoning</h2>
  ${expert.length ? '<ul>' + expert.map((l) => `<li>entry ${entryLink(l.src_entry_id)} ${esc(l.relation)} entry ${entryLink(l.dst_entry_id)}: ${esc(l.rationale)} <span class="muted small">(recorded ${tm(l.known_at)})</span></li>`).join('') + '</ul>' : `<p class="muted">No expert links ${S.replay ? 'yet' : 'recorded'}.</p>`}`;
  return { html, mount() { $('#know').innerHTML = knowledgeChart(i, d.entries, $('#know').clientWidth); } };
};

const TL = { t0: null, t1: null, typical: false };
PAGES.timeline = async (parts) => {
  const name = parts[1] ? decodeURIComponent(parts[1]) : (S.elements.find((e) => e.kind === 'readout_box') || S.elements[0]).name;
  const d = await api('timeline', { element: name });
  if (TL.t0 == null) { TL.t0 = d.t0; TL.t1 = d.t1; }
  const kinds = ['experiment', 'detector', 'subdetector', 'readout_box', 'lv_supply', 'fed'];
  const html = `<h1>What is in the Record: timeline of ${esc(name)}</h1>
  <p class="lead">${d.colour_by === 'box' ? `Readings from ${d.boxes.map(esc).join(', ')}` : `Readings from all ${d.boxes.length} readout boxes, one line each, coloured by subdetector`}, with what was recorded about ${esc(name)} and the parts around it.</p>
  <div class="filters">
    <label>Element <select id="tl-el">${kinds.map((k) => `<optgroup label="${k.replace('_', ' ')}">${S.elements.filter((e) => e.kind === k).map((e) => `<option${e.name === name ? ' selected' : ''}>${esc(e.name)}</option>`).join('')}</optgroup>`).join('')}</select></label>
    <button data-tl="in">Zoom in</button><button data-tl="out">Zoom out</button><button data-tl="left">&#9664;</button><button data-tl="right">&#9654;</button>
    <button data-tl="all">Whole calendar</button>
    <label><input type="checkbox" id="tl-typ"${TL.typical ? ' checked' : ''}> Vertical scale: typical range</label>
  </div>
  ${d.colour_by === 'subdetector' ? `<div class="key">${d.groups.map((g, k) => `<span><i class="c${k + 1}"></i>${esc(g)}</span>`).join('')}</div>`
    : d.boxes.length > 1 ? `<div class="key">${d.boxes.map((b, k) => `<span><i class="c${k + 1}"></i>${esc(b)}</span>`).join('')}</div>` : ''}
  <div id="tl"></div>
  <details open><summary>How to read this</summary>
  <ul><li><b>Voltage and temperature are not stored in the Record.</b> They are fetched from the source archive for the range in view. Zoomed out, each drawn point is the mean of the samples it covers; zoom in far enough and every sample is drawn. <a href="#/built">Why the Record does not keep them.</a></li>
  <li><b>Reading status</b> is what the Record keeps instead: one entry each time a box's reading changes status (drifting, low, high, off, back to normal). Each bar runs from one change to the next.</li>
  <li><b>Dead channels, hot channels and occupancy</b> are per-run numbers, also fetched from a source (the data-quality archive), drawn as a flat segment across each run. The Record keeps only <b>quality status</b> changes.</li>
  <li><b>Not certified yet</b>: runs whose certification is not complete for the subdetector. Once it is, a lumisection is good unless a <b>certified bad</b> range covers it; good is not stored.</li>
  <li>The rows include entries filed on other parts that <b>concern</b> this one, for example a logbook note filed on a supply that names this box.</li>
  <li>The rows at the bottom are other entries: downtime, certified-bad ranges, state changes, fault events and logbook notes. Hover to read one, click to open it. Dashed lines are incidents.</li>
  <li>Drag across the chart to zoom into a time range; double-click to see everything. "Typical range" ignores the most extreme 5% at each end, so a small drift stays visible next to a trip to zero.</li></ul></details>`;
  return { html, mount() {
    const redraw = mountTimeline($('#tl'), d, TL, name);
    $('#tl-el').addEventListener('change', (ev) => { location.hash = `#/timeline/${encodeURIComponent(ev.target.value)}`; });
    $('#tl-typ').addEventListener('change', (ev) => { TL.typical = ev.target.checked; redraw(); });
    document.querySelectorAll('[data-tl]').forEach((b) => b.addEventListener('click', () => {
      const w = TL.t1 - TL.t0, mid = (TL.t0 + TL.t1) / 2, a = b.dataset.tl;
      if (a === 'in') { TL.t0 = mid - w / 4; TL.t1 = mid + w / 4; }
      if (a === 'out') { TL.t0 = mid - w; TL.t1 = mid + w; }
      if (a === 'left') { TL.t0 -= w / 3; TL.t1 -= w / 3; }
      if (a === 'right') { TL.t0 += w / 3; TL.t1 += w / 3; }
      if (a === 'all') { TL.t0 = d.t0; TL.t1 = d.t1; }
      TL.t0 = Math.round(Math.max(d.t0 - 86400, TL.t0)); TL.t1 = Math.round(Math.min(d.t1 + 86400, TL.t1));
      redraw();
    }));
  } };
};
/* Draws the readings-and-records chart into a host. Used by the Timeline page and by Replay. */
const STATUS_CLS = { 'drifting down': 'warn', 'drifting up': 'warn', low: 'bad', high: 'bad', off: 'down', 'channels lost': 'down', 'hot channels': 'bad', 'occupancy high': 'warn', 'occupancy low': 'warn' };
function mountTimeline(host, d, view, name) {
  const rowsOf = (dd) => dd.strip.map((r) => ({ label: r.row, items: r.items.map((it) => ({
    t0: it.t0, ...(['Stable beams', 'Downtime', 'Not certified yet', 'Certified bad', 'Reading status', 'Quality status'].includes(r.row) ? { t1: it.t1 ?? null } : {}),
    cls: { 'Stable beams': 'beam', Downtime: 'down', 'Not certified yet': 'pending', 'Certified bad': 'bad', 'Reading status': STATUS_CLS[it.value] || 'warn', 'Quality status': STATUS_CLS[it.value] || 'warn', 'State change': 'mk', 'Fault event': it.planned ? 'mk' : 'mk crit', 'Logbook note': it.routine ? 'note routine' : 'note' }[r.row],
    shape: { 'State change': 'diamond', 'Fault event': 'tri', 'Logbook note': 'tick' }[r.row],
    tip: `${fmt(it.t0)}\n${it.text}`, go: it.id ? `#/entry/${it.id}` : undefined })) }));
  let cur = d, token = 0;
  const draw = () => {
    const colour = (s, i) => ({ ...s, cls: cur.colour_by === 'subdetector' ? `c${cur.groups.indexOf(s.group) + 1} thin` : `c${i + 1}` });
    const panels = cur.panels.map((p) => ({ ...p, series: p.series.map(colour), label: p.from_source ? `${p.label}, from the source archive` : p.label }));
    const cfg = { t0: view.t0, t1: view.t1, width: host.clientWidth, typical: view.typical, panels, rows: rowsOf(cur),
      vlines: cur.incidents.map((i) => ({ t: i.t_start, cls: 'inc', label: `#${i.id}`, tip: `${i.title} (${i.status})`, go: `#/incident/${i.id}` })).concat(S.replay ? [{ t: S.asOf, cls: 'asof' }] : []),
      aria: `readings and recorded events for ${name}` };
    const chart = buildChart(cfg);
    host.innerHTML = chart.svg;
    wireChart(host, chart, cfg, { zoom: (a, b) => go(a, b), reset: () => go(d.t0, d.t1) });
  };
  // Readings are fetched from the source for the range in view, so zooming in reaches full resolution.
  const go = async (a, b) => {
    view.t0 = a; view.t1 = b;
    const my = ++token;
    const pad = Math.round((b - a) * 0.05);
    const fresh = await api('timeline', { element: name, t0: a - pad, t1: b + pad });
    if (my !== token) return;
    cur = fresh; draw();
  };
  if (d.range && (d.range[0] > view.t0 || d.range[1] < view.t1 || d.range[1] - d.range[0] > 3 * (view.t1 - view.t0))) go(view.t0, view.t1);
  else draw();
  return () => go(view.t0, view.t1);
}

/* 4. scenarios in this demo ---------------------------------------------------------- */
const DV = { mode: null, idx: 0 };
async function planted() {
  if (!S.meta.has_planted) return null;
  if (!S.planted) S.planted = await api('demo/device', {}, false);
  return S.planted;
}
PAGES.scenarios = async () => {
  const d = await planted();
  if (!d) return { html: '<h1>Scenarios in this demo</h1><p>No planted.json was found next to this Record.</p>' };
  const modes = Object.keys(d.modes).filter((m) => d.cases.some((c) => c.mode === m));
  if (!modes.includes(DV.mode)) { DV.mode = modes[0]; DV.idx = 0; }
  const cases = d.cases.filter((c) => c.mode === DV.mode);
  const c = cases[Math.min(DV.idx, cases.length - 1)];
  const html = `${EXPLAINER('Read from the generator\'s own notes (planted.json), not from the Record. A real Record has no such list.')}
  <h1>Scenarios in this demo</h1>
  <p class="lead">The generator planted ${d.cases.length} situations into the routine background. They are the worked examples of this demo. A real Record has no such list: this page reads the generator's own notes, kept in a separate file, not the Record.</p>
  <div class="tabs">${modes.map((m) => `<button data-dv-mode="${m}" class="${m === DV.mode ? 'on' : ''}">${esc(d.modes[m].title)} (${d.cases.filter((x) => x.mode === m).length})</button>`).join('')}</div>
  <div class="note"><b>${esc(d.modes[DV.mode].title)}.</b> ${esc(d.modes[DV.mode].story)}</div>
  ${cases.length > 1 ? `<div class="tabs">${cases.map((x, k) => `<button data-dv-idx="${k}" class="${x.id === c.id ? 'on' : ''}">${esc(x.true_element)} · ${fmtShort(x.t_event)}</button>`).join('')}</div>` : ''}
  <div class="card"><dl class="facts">
    <dt>Where the fault really is</dt><dd>${elLink(c.true_element)}</dd><dt>Where the crew sees it</dt><dd>${esc(c.reported_element)}</dd>
    <dt>Starts</dt><dd>${tm(c.t_event)}</dd>
    <dt>In the Record as</dt><dd>${c.incident ? incLink(c.incident.id, c.incident.title) + ` <button data-replay="${c.incident.id}">Replay</button>` : `no incident, because nothing is wrong <button data-free="${c.ask_at}">look at the Record at that moment</button>`}</dd>
  </dl></div>
  <h2>What the generator wrote for it</h2>
  <p class="muted small">Compare "happened" with "known": the gap is how late that piece reaches the Record.</p>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}<th>Delay</th></tr>${c.entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}"><td>${esc(e.role)}</td>
    <td class="t">${tm(e.t_start)}</td><td class="t">${tm(e.known_at)}</td><td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td><td class="what">${esc(describe(e))}</td><td class="t">${dur(e.known_at - e.t_start)}</td></tr>`).join('')}</table></div>`;
  return { html, mount() {
    document.querySelectorAll('[data-dv-mode]').forEach((b) => b.addEventListener('click', () => { DV.mode = b.dataset.dvMode; DV.idx = 0; render(); }));
    document.querySelectorAll('[data-dv-idx]').forEach((b) => b.addEventListener('click', () => { DV.idx = +b.dataset.dvIdx; render(); }));
  } };
};

/* 5. replay -------------------------------------------------------------------------- */
function answerKey(caseFor) {
  if (!caseFor) return '<p class="muted">The generator has no note for this one.</p>';
  const x = caseFor.expected;
  return `<dl class="facts"><dt>Planted situation</dt><dd>${esc(caseFor.mode.replace(/_/g, ' '))}</dd><dt>Really on</dt><dd>${esc(caseFor.true_element)}</dd>
    <dt>Crew's question</dt><dd>${esc(caseFor.question)} <span class="muted">(asked at ${tm(caseFor.ask_at)})</span></dd>
    <dt>Honest answer at that moment</dt><dd><b>${esc(x.verdict.replace(/_/g, ' '))}</b>; next step: ${esc(x.next_step.replace(/_/g, ' '))}${x.precedents.length ? '; seen before as ' + x.precedents.map((p) => '#' + p).join(' ') : ''}</dd></dl>`;
}
const precTable = (rows) => rows.length ? `<div class="tablewrap"><table><tr><th>#</th><th>Started</th><th>Element</th><th>Title</th><th>Status then</th><th>Recovery known then</th><th>Cause known then</th></tr>
  ${rows.map((r) => `<tr class="click" data-go="#/incident/${r.id}"><td class="num">${r.id}</td><td class="t">${tm(r.t_start)}</td><td>${esc(r.element)}</td><td>${esc(r.title)}</td><td>${statusCell(r.status)}</td>
    <td class="what">${r.recovery_action ? esc(r.recovery_action) : empty()}</td><td class="what">${r.confirmed_cause ? esc(r.confirmed_cause) : empty()}</td></tr>`).join('')}</table></div>` : '<p class="muted">None.</p>';
PAGES.replay = async () => {
  const pl = await planted();
  const r = S.replay;
  const reveal = `<label><input type="checkbox" id="rv"${S.reveal ? ' checked' : ''}> Reveal the answer key</label> <span class="muted small">the generator's own notes, never part of the Record</span>`;
  if (!r) {
    const end = S.meta.latest_known_at;
    const d = await api('precedents', {});
    const cases = pl ? Object.fromEntries(pl.cases.filter((c) => c.incident_id).map((c) => [c.incident_id, c])) : {};
    const others = pl ? pl.cases.filter((c) => !c.incident_id) : [];
    const list = (ids) => (ids.length ? ids.map((x) => `#${x}`).join(' ') : '<span class="muted">no</span>');
    void end;
    const html = `<h1>Replay</h1>
    <p class="lead">Every entry has two times: when it happened and when the Record learned of it. A replay winds the Record back to a moment and shows only what it knew then, so you can step through an incident the way a crew would have met it.</p>
    <div class="note">Everywhere else in this GUI you see the finished Record. During a replay, every page shows the Record at the replay's moment, and a bar at the top lets you step forward and leave.</div>
    <h2>Pick an incident to replay</h2>
    <p class="muted small">"Seen before?" asks, at the moment a crew would first ask, whether an earlier incident was already on record. Two possible rules are shown: an earlier incident that concerns one of the same parts, or one with the same kind of symptom on any element.</p>
    <div class="filters">${pl ? reveal : ''}</div>
    <div class="tablewrap"><table class="sortable"><tr><th></th><th>#</th><th>Started</th><th>Element</th><th>Title</th><th>Seen before on a shared part?</th><th>Seen before with the same symptom?</th>${S.reveal ? '<th class="key-col">Planted situation</th><th class="key-col">Honest answer when asked</th>' : ''}</tr>
    ${d.incidents.map((i) => `<tr><td><button class="primary" data-replay="${i.id}">Replay</button></td><td class="num">${i.id}</td><td class="t" data-sort="${i.t_start}">${tm(i.t_start)}</td><td>${esc(i.element)}</td><td>${incLink(i.id, i.title)}</td>
      <td data-sort="${i.same_element.length}">${list(i.same_element)}</td><td data-sort="${i.same_symptom.length}">${list(i.same_symptom)}</td>${S.reveal ? `<td class="key-col">${cases[i.id] ? esc(cases[i.id].mode.replace(/_/g, ' ')) : ''}</td><td class="key-col">${cases[i.id] ? esc(cases[i.id].expected.verdict.replace(/_/g, ' ')) + ', ' + esc(cases[i.id].expected.next_step.replace(/_/g, ' ')) : ''}</td>` : ''}</tr>`).join('')}</table></div>
    <p>Across these ${d.incidents.length} incidents, the shared-part rule says "seen before" for <b>${d.known_by_same_element}</b>, the same-symptom rule for <b>${d.known_by_same_symptom}</b>, and they disagree on <b>${d.disagree}</b>.</p>
    ${S.reveal && others.length ? `<h2>Planted situations that are not incidents</h2><ul>${others.map((c) => `<li>${esc(c.mode.replace(/_/g, ' '))} on ${esc(c.true_element)} at ${tm(c.t_event)}: the honest answer is "${esc(c.expected.verdict.replace(/_/g, ' '))}". <button data-free="${c.ask_at}">Look at the Record when the crew asks</button></li>`).join('')}</ul>` : ''}`;
    return { html, mount() { if ($('#rv')) $('#rv').addEventListener('change', (ev) => { S.reveal = ev.target.checked; render(); }); } };
  }
  if (r.id == null) {
    const d = r.prev != null && r.prev < S.asOf ? await api('diff', { since: r.prev }) : null;
    const html = `<h1>The Record at ${tm(S.asOf)}</h1>
    <p class="lead">A past moment, without following a particular incident. A step is the next moment the Record learned anything.</p>
    ${stepControls()}
    ${replaySections(null)}
    ${d ? `<h2>Learned in the last step</h2><p>${d.n_entries} entries, ${d.n_links} links, ${d.incident_changes.length} incident changes since ${tm(d.from)}.</p>
      ${d.incident_changes.length ? '<ul>' + d.incident_changes.map((c) => `<li>${tm(c.t)} · ${incLink(c.incident_id, c.title)}: ${esc(c.what)}</li>`).join('') + '</ul>' : ''}
      <div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows(d.entries)}</table></div>` : ''}`;
    return { html, mount() { wireSteps(); mountReplaySections(null); } };
  }
  const d = await api('replay', r.prev != null && r.prev < S.asOf ? { id: r.id, since: r.prev } : { id: r.id });
  const i = d.incident, f = d.frame, p = d.precedents;
  const caseFor = pl ? pl.cases.find((c) => c.incident_id === r.id) : null;
  const roles = [...new Set(d.entries.filter((e) => e.role).map((e) => (e.role === 'closing_note' ? 'cause' : e.role)))];
  const html = `<h1>Replay of incident #${f.id}: ${esc(f.title)}</h1>
  <p class="lead">The problem starts at ${tm(f.t_start)}. You are at <b>${tm(S.asOf)}</b>, ${dur(Math.abs(S.asOf - f.t_start))} ${S.asOf >= f.t_start ? 'after' : 'before'} the start.</p>
  ${stepControls()}
  <h2>How knowledge has arrived so far</h2>
  ${(() => { const past = r.steps.filter((x) => x <= S.asOf), k = past.length, said = k ? d.step_notes[String(past[k - 1])] : null;
    return `<p class="stepnow"><b>${k ? `Step ${k} of ${r.steps.length}` : 'Before the first step'}</b>${said ? `: the Record learned ${said.map(esc).join('; ')}` : ''}</p>`; })()}
  <p class="muted small">A <b>step</b> is a moment at which the Record learned something about this problem: a symptom was recorded, the incident was opened, an entry or a part was linked to it, or a label was written. Hover a step to see what; click to go there. Below, each entry is drawn when it happened (with what happened written above it) and when it became known. The shaded part is still in the future; the scale is compressed.</p>
  <div class="key"><span><i class="c0"></i>a symptom on record, not yet linked to an incident</span>${roles.map((x) => `<span><i class="${ROLE_CLASS[x]}"></i>${ROLE_LABEL[x] || x}</span>`).join('')}</div>
  <div id="know"></div>
  <div class="cols"><div class="card"><b>What the Record says about this problem now</b>
    ${i ? `<dl class="facts"><dt>Status</dt><dd>${statusCell(i.status)}</dd><dt>Recovery action</dt><dd>${i.recovery_action ? esc(i.recovery_action) : empty()}</dd>
      <dt>Confirmed cause</dt><dd>${i.confirmed_cause ? esc(i.confirmed_cause) : empty()}</dd><dt>Certification</dt><dd>${i.certification ? esc(i.certification) : empty()}</dd></dl>`
      : `<p>Nothing yet as an incident. ${d.entries.length} symptom entries are on record, but nobody has grouped them: the incident is opened at ${tm(f.opened_at)}.</p>`}</div>
  <div class="card"><b>Learned in the last step</b>
    ${d.learned ? ((d.learned.changes.length || d.learned.entries.length) ? '<ul>' + d.learned.changes.map((c) => `<li>${esc(c.what)}</li>`).join('') + d.learned.entries.map((e) => `<li>entry ${entryLink(e.id)}: ${esc(describe(e))}</li>`).join('') + '</ul>' : '<p class="muted">Entries already on record were attached to the incident.</p>') : '<p class="muted">Press "next step".</p>'}</div></div>
  <div id="agent-panel" class="agent"><b>What the agent would say at this moment</b> <span class="muted small">asking…</span></div>
  <div class="compare"><b>Compare with an LLM brain:</b> <select id="cmp-brain"><option value="">choose a profile…</option></select>
    <button id="cmp-ask">Ask</button> <span id="cmp-status" class="muted small"></span></div>
  <div id="agent-panel-2"></div>
  <details ${RS.parts ? 'open' : ''} data-rs="parts"><summary><b>Parts this problem concerns, as known now</b> (${(d.parts || []).length})</summary>${partsTable(d.parts)}</details>
  ${replaySections(f.element)}
  <details ${RS.seen ? 'open' : ''} data-rs="seen"><summary><b>Has this been seen before?</b> ${p.same_element.length} on a shared part, ${p.same_symptom.length} with the same kind of symptom</summary>
  <p class="muted small">Earlier incidents on record at this moment, as the Record knew them now. Symptom kinds of this problem so far: <span class="mono">${p.symptom_kinds.map(esc).join(', ') || 'none on record yet'}</span>.</p>
  <h3>Concerning one of the same parts (${p.same_element.length})</h3>${precTable(p.same_element)}
  <h3>With the same kind of symptom, on any element (${p.same_symptom.length})</h3>${precTable(p.same_symptom)}</details>
  <details ${RS.entries ? 'open' : ''} data-rs="entries"><summary><b>Entries on record for this problem</b> (${d.entries.length})</summary>
  <p class="muted small">Before the incident is opened, only its symptoms are listed: they are what the crew is looking at. Evidence that an expert links later appears when that link is recorded, not before.</p>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}</tr>${entryRows(d.entries, (e) => `<td>${e.role ? esc(e.role) : '<span class="unknown">not yet linked</span>'}</td>`)}</table></div></details>
  ${pl ? `<details ${S.reveal ? 'open' : ''} id="rvd"><summary><b>Answer key</b> <span class="muted small">the generator's own notes, never part of the Record</span></summary><div class="note keynote">${answerKey(caseFor)}</div></details>` : ''}`;
  return { html, mount() {
    wireSteps();
    $('#know').innerHTML = knowledgeChart({ t_start: f.t_start }, d.entries, $('#know').clientWidth, r.steps, d.step_notes);
    if ($('#rvd')) $('#rvd').addEventListener('toggle', (ev) => { S.reveal = ev.target.open; });
    mountReplaySections(f.element);
    mountAgent(r.id, caseFor);
  } };
};
const VERDICT_CLS = { known: 'v-known', uncertain: 'v-uncertain', new: 'v-new' };
const CMP = { brain: '' };
async function mountAgent(iid, caseFor) {
  const host = $('#agent-panel');
  if (!host) return;
  let a;
  try { a = await api('agent', { id: iid }); } catch (e) { host.innerHTML = `<b>What the agent would say at this moment</b><p>${esc(e.message)}</p>`; return; }
  renderAgent(host, a, caseFor);
  // the LLM comparison: profiles come from ~/.config/orchestra/llm.yaml on the server; keys never reach the browser
  const sel = $('#cmp-brain'), status = $('#cmp-status');
  const pr = await api('profiles', {}, false);
  if (!pr.profiles.length) {
    sel.disabled = true; $('#cmp-ask').disabled = true;
    status.textContent = pr.error || 'No LLM profiles configured: create ~/.config/orchestra/llm.yaml on this machine.';
    return;
  }
  sel.innerHTML += pr.profiles.map((p) => `<option value="${esc(p.name)}"${p.key_available ? '' : ' disabled'}${p.name === CMP.brain ? ' selected' : ''}>${esc(p.name)}: ${esc(p.model)} at ${esc(p.host)}${p.key_available ? '' : ' (key not found: ' + esc(p.key_source) + ')'}</option>`).join('');
  const ask = async () => {
    CMP.brain = sel.value;
    if (!CMP.brain) return;
    const host2 = $('#agent-panel-2');
    host2.className = 'agent agent-llm';
    host2.innerHTML = `<b>What the agent would say at this moment</b> <span class="brain brain-model">LLM brain</span> <span class="muted small">asking ${esc(CMP.brain)}… this sends the question and the Record entries the model asks for to that endpoint</span>`;
    try { renderAgent(host2, await api('agent', { id: iid, brain: CMP.brain }), caseFor); } catch (e) { host2.innerHTML = `<b>LLM brain</b><p class="bad-text">${esc(e.message)}</p>`; }
  };
  $('#cmp-ask').addEventListener('click', ask);
  if (CMP.brain) ask();
}
function renderAgent(host, a, caseFor) {
  if (!a.trigger) { host.innerHTML = `<b>What the agent would say at this moment</b><p class="muted">${esc(a.message)}</p>`; return; }
  const p = a.proposal, cited = a.cited, log = a.log;
  const pct = (x) => `${Math.round(x * 100)}%`;
  const bar = (x) => `<span class="cbar"><span style="width:${pct(x)}"></span><i style="left:${pct(a.settings.new_below)}"></i><i style="left:${pct(a.settings.known_at_least)}"></i></span>`;
  const call = (qid) => log[qid - 1];
  const argText = (c) => Object.entries(c.args).map(([k, v]) => `${k}=${Array.isArray(v) ? '[' + v.join(', ') + ']' : (['t', 't0', 't1', 'before'].includes(k) ? fmt(v) : v)}`).join(', ');
  const BRAINS = { scripted: ['Scripted brain', 'a fixed procedure, no language model'], model: ['LLM brain', 'a language model calling the same tools'] };
  const [brainName, brainWhat0] = BRAINS[p.brain] || [p.brain, ''];
  const brainWhat = p.brain_label ? `${brainWhat0} (${p.brain_label})` : brainWhat0;
  host.innerHTML = `<div class="agent-head"><b>What the agent would say at this moment</b>
      <span class="brain brain-${esc(p.brain)}">${brainName}</span><span class="muted small">${brainWhat}</span></div>
    <div class="io-agent">
      <div class="io-in"><div class="io-label">Input: the question</div>
        <p>"${esc(a.trigger.question)}"</p>
        <dl class="facts small"><dt>Asked at</dt><dd>${tm(a.trigger.as_of)}</dd><dt>Seen on</dt><dd>${elLink(a.trigger.part)}</dd>
          <dt>Symptoms given</dt><dd>${a.trigger.symptom_ids.length} entries on record</dd></dl></div>
      <div class="io-out"><div class="io-label">Output: the ${brainName.toLowerCase()}'s answer ${a.accepted ? '<span class="ok-text">passed the check</span>' : '<span class="bad-text">rejected by the check</span>'}</div>
        <dl class="facts answer">
          <dt>Verdict</dt><dd><span class="verdict ${VERDICT_CLS[p.verdict]}">${p.verdict}</span> ${p.verdict === 'known' ? 'seen before' : p.verdict === 'new' ? 'not seen before' : 'possibly seen before'}</dd>
          <dt>Confidence</dt><dd>${bar(p.confidence)} <b>${pct(p.confidence)}</b> <span class="muted small">known from ${pct(a.settings.known_at_least)}, new below ${pct(a.settings.new_below)}</span></dd>
          <dt>Next step</dt><dd><b>${p.next_step.replace('_', ' ')}</b></dd>
          <dt>Part at fault</dt><dd>${elLink(p.element)}</dd>
          <dt>Precedent</dt><dd>${p.precedent ? incLink(p.precedent) : '<span class="muted">none</span>'}</dd>
          <dt>Diagnosis</dt><dd>${esc(p.diagnosis)}</dd>
          ${p.notes.length ? `<dt>Notes</dt><dd class="small">${p.notes.map(esc).join('<br>')}</dd>` : ''}
        </dl>
        ${a.problems.length ? `<p class="bad-text small">${a.problems.map(esc).join('<br>')}</p>` : ''}</div></div>
    <div class="io-label" style="margin-top:10px">How it got there</div>
    <details ${p.candidates.length ? 'open' : ''}><summary><b>Earlier incidents recalled</b> (${p.candidates.length}) and how sure it is about each</summary>
      ${p.candidates.length ? `<div class="tablewrap"><table><tr><th>#</th><th>Title</th><th>Match</th><th>Confidence</th><th>How it was reached</th><th>What was done then</th></tr>
      ${p.candidates.map((c) => `<tr><td>${incLink(c.id)}</td><td>${esc(c.title)}</td><td>${c.signature === 'both' ? 'shared part and symptom' : c.signature === 'symptom' ? 'same symptom' : 'shared part'}<br><span class="small muted">${[...c.shared_parts, ...c.shared_kinds].map(esc).join(', ')}</span></td>
        <td class="t">${bar(c.confidence)} ${pct(c.confidence)}</td><td class="small">${c.steps.map(esc).join('<br>')}</td><td class="what small">${c.recovery_action ? esc(c.recovery_action) : empty()}</td></tr>`).join('')}</table></div>`
        : '<p class="muted">None share a part or a kind of symptom with this problem.</p>'}
      <p class="small muted">Verdict: known from ${pct(a.settings.known_at_least)}, new below ${pct(a.settings.new_below)}. Reviews learned from so far: ${Object.entries(a.learned).map(([k, v]) => `${k} ${v.confirmed} confirmed / ${v.rejected} rejected`).join('; ')}.</p></details>
    <details><summary><b>Evidence it cites</b> (${p.supporting.length}): each entry came back from a logged tool call</summary>
      <div class="tablewrap"><table><tr><th>Why</th><th>Entry</th><th>What</th><th>Returned by</th></tr>${p.supporting.map((c) => `<tr><td class="small">${esc(c.why)}</td><td>${entryLink(c.entry_id)}</td>
        <td class="what small">${cited[c.entry_id] ? esc(cited[c.entry_id].short) : ''}</td><td class="small">query ${c.query_id}: ${esc(call(c.query_id).tool)}</td></tr>`).join('')}</table></div></details>
    <details><summary><b>Tool calls</b> (${log.length}), all as of ${fmt(a.trigger.as_of)}</summary>
      <ol class="calls">${log.map((c) => `<li><span class="mono">${esc(c.tool)}(${esc(argText(c))})</span><br><span class="small">${esc(c.summary)}</span></li>`).join('')}</ol></details>
    ${S.reveal && caseFor ? `<div class="note keynote small"><b>Answer key:</b> the honest answer when the crew first asks is ${esc(caseFor.expected.verdict)}, ${esc(caseFor.expected.next_step.replace(/_/g, ' '))}.</div>` : ''}`;
}
/* Collapsible views inside the replay page. They are the same drawings as the full pages,
   fed with the same as-of data. */
const RS = { map: false, tl: false, seen: true, entries: false, parts: true, view: null, viewFor: null };
function replaySections(element) {
  return `<details ${RS.map ? 'open' : ''} data-rs="map"><summary><b>The detector at this moment</b></summary><div id="rs-map"></div><p class="small"><a href="#/detector">Open the detector page</a></p></details>
  <details ${RS.tl ? 'open' : ''} data-rs="tl"><summary><b>Timeline${element ? ' of ' + esc(element) : ''} up to this moment</b></summary><div id="rs-tl"></div>
    <p class="small">Drag to zoom, double-click for the whole calendar. <a href="#/timeline${element ? '/' + encodeURIComponent(element) : ''}">Open the timeline page</a></p></details>`;
}
function mountReplaySections(element) {
  const fill = async (key) => {
    if (key === 'map') { const m = await api('map'); $('#rs-map').innerHTML = mapHeader(m) + mapSvg(m, $('#rs-map').clientWidth); }
    if (key === 'tl') {
      const name = element || (S.elements.find((e) => e.kind === 'detector') || S.elements[0]).name;
      const t = await api('timeline', { element: name });
      const from = S.replay.id ? S.replay.ask : S.asOf;
      if (RS.viewFor !== S.replay.id + ':' + name) { RS.view = { t0: Math.max(t.t0, from - 8 * 3600), t1: Math.min(t.t1, Math.max(from, S.asOf) + 4 * 3600), typical: false }; RS.viewFor = S.replay.id + ':' + name; }
      mountTimeline($('#rs-tl'), t, RS.view, name);
    }
  };
  document.querySelectorAll('details[data-rs]').forEach((el) => {
    const key = el.dataset.rs;
    if (el.open) fill(key);
    el.addEventListener('toggle', () => { RS[key] = el.open; if (el.open) fill(key); });
  });
}

/* 6. the agent ------------------------------------------------------------------------ */
const OUTCOME = {
  right: ['right', 'v-known', 'a precedent it called known was confirmed later, or it called a problem new and none was'],
  'too cautious': ['too cautious', 'v-uncertain', 'it named the right precedent but was not sure enough to call it known'],
  'right to doubt': ['right to doubt', 'v-uncertain', 'it was unsure, and the precedent was later rejected'],
  wrong: ['wrong', 'v-wrong', 'it called a problem known, and the precedent was later rejected'],
  missed: ['missed', 'v-wrong', 'it called a problem new, but a precedent was later confirmed'],
  'not reviewed yet': ['not reviewed yet', 'v-pending', 'no review of this incident is on record yet'],
};
PAGES.agent = async () => {
  const d = await api('agent_report');
  const pl = S.reveal ? await planted() : null;
  const key = pl ? Object.fromEntries(pl.cases.filter((c) => c.incident_id).map((c) => [c.incident_id, c])) : {};
  const rows = d.rows, pct = (x) => `${Math.round(x * 100)}%`, set = d.settings;
  const count = (f) => rows.filter(f).length;
  const bins = [['new (below ' + pct(set.new_below) + ')', (r) => r.verdict === 'new'], ['uncertain', (r) => r.verdict === 'uncertain'], ['known (from ' + pct(set.known_at_least) + ')', (r) => r.verdict === 'known']];
  const outcomes = Object.keys(OUTCOME).filter((o) => rows.some((r) => r.outcome === o));
  const badge = (o) => `<span class="verdict ${OUTCOME[o][1]}" title="${esc(OUTCOME[o][2])}">${OUTCOME[o][0]}</span>`;
  const html = `<h1>The agent</h1>
  <p class="lead">What the diagnosis agent does, and how it did on every incident in this Record, each asked at the moment its crew would first have asked.</p>
  <h2>What it does</h2>
  <div class="flow">
    <div class="box"><b>1. Trigger</b>a question, the moment, where the problem shows, and the symptom entries on record</div><span class="arrow">&#8594;</span>
    <div class="box real"><b>2. Tools</b>six read-only calls, all as of the moment, all logged: search_incidents, get_incident, state, events, co_occurring, series</div><span class="arrow">&#8594;</span>
    <div class="box real"><b>3. Recall</b>earlier incidents sharing a part or a kind of symptom</div><span class="arrow">&#8594;</span>
    <div class="box real"><b>4. Confidence</b>per recalled incident: learned from past reviews, raised by evidence found again</div><span class="arrow">&#8594;</span>
    <div class="box real"><b>5. Proposal</b>verdict, next step, part, diagnosis, cited evidence; checked before anyone sees it</div></div>
  <div class="cols"><div class="card"><b>The scripted brain</b>, used here: a fixed procedure, no language model. Look at the symptoms; recall; open each candidate; check whether the parts its experts suspected or blamed are in the same abnormal state now; look at the 12 hours before; fetch a supply's voltage from the source if one is involved; score; fill in the proposal. A <b>model brain</b> can take its place through any OpenAI-compatible endpoint, with the same tools and the same check; it has not been run against a real model yet.</div>
  <div class="card"><b>The confidence</b>, per recalled incident:<ul class="rules">
    <li>starting value for its kind of match, learned from precedent reviews known at the moment, with an expert prior: ${Object.entries(set.priors).map(([k, v]) => `${k === 'both' ? 'shared part and symptom' : k === 'symptom' ? 'same symptom' : 'shared part'} as if ${v.confirmed} confirmed / ${v.rejected} rejected`).join('; ')}</li>
    <li>odds x${set.evidence_factor} for each thing its experts relied on that is found again now</li>
    <li>known from ${pct(set.known_at_least)}; uncertain from ${pct(set.new_below)}; new below</li></ul>
    <p class="small muted">The <b>check</b> rejects any cited entry that no logged tool call returned, and "known" without a precedent.</p></div></div>
  ${EXPLAINER('In this demo the trigger takes the symptom entries from the incident the generator later writes, standing in for the crew pointing at what they see; and the precedent reviews the confidence learns from were invented by the generator, knowing the truth.')}
  <h2>How it did</h2>
  <p class="muted small">Each incident is asked at the moment its crew would first have asked (five minutes after its first symptom), with only what the Record knew then. It is judged by the precedent reviews written after the incident was closed: the Record's own later verdict, not the answer key.</p>
  <div class="tiles">${[['incidents asked', rows.length], ...bins.map(([l, f]) => [l, count(f)])].map(([l, n]) => `<div class="tile"><b>${n}</b><span>${l}</span></div>`).join('')}</div>
  <div class="tablewrap"><table class="matrix"><tr><th>Verdict \\ judged later</th>${outcomes.map((o) => `<th>${badge(o)}</th>`).join('')}</tr>
    ${bins.map(([l, f]) => `<tr><td><b>${l}</b></td>${outcomes.map((o) => { const n = count((r) => f(r) && r.outcome === o); return `<td class="num">${n || ''}</td>`; }).join('')}</tr>`).join('')}</table></div>
  <p class="small muted">${outcomes.map((o) => `${badge(o)} ${esc(OUTCOME[o][2])}`).join('<br>')}</p>
  <h2>How the learned starting values moved</h2>
  <p class="muted small">Each line is the starting confidence for one kind of match, as precedent reviews accumulate. A recurrence of the same symptom on a different part starts at ${pct(set.priors.symptom.confirmed / (set.priors.symptom.confirmed + set.priors.symptom.rejected))} and rises as reviews confirm that such matches are real precedents.</p>
  <div class="key"><span><i class="c1"></i>shared part and symptom</span><span><i class="c2"></i>same symptom</span><span><i class="c3"></i>shared part only</span></div>
  <div id="learn"></div>
  <h2>Every incident</h2>
  <div class="filters"><label><input type="checkbox" id="rv"${S.reveal ? ' checked' : ''}> Reveal the answer key</label> <span class="muted small">the generator's own notes, never part of the Record</span></div>
  <p class="small muted">Click a column header to sort.</p>
  <div class="tablewrap"><table class="sortable"><tr><th>#</th><th>Title</th><th>Asked</th><th>Verdict</th><th>Confidence</th><th>Precedent</th><th>Next step</th><th>Judged later</th>${pl ? '<th class="key-col">Answer key</th>' : ''}<th></th></tr>
  ${rows.map((r) => `<tr><td class="num">${r.id}</td><td>${incLink(r.id, r.title)}</td><td class="t" data-sort="${r.asked}">${tm(r.asked)}</td>
    <td data-sort="${['new', 'uncertain', 'known'].indexOf(r.verdict)}"><span class="verdict ${VERDICT_CLS[r.verdict]}">${r.verdict}</span></td>
    <td class="t" data-sort="${r.confidence}"><span class="cbar"><span style="width:${pct(r.confidence)}"></span><i style="left:${pct(set.new_below)}"></i><i style="left:${pct(set.known_at_least)}"></i></span> ${pct(r.confidence)}</td>
    <td data-sort="${r.precedent ?? -1}">${r.precedent ? incLink(r.precedent) : '<span class="muted">none</span>'}</td><td>${r.next_step.replace('_', ' ')}</td><td data-sort="${r.outcome}">${badge(r.outcome)}</td>
    ${pl ? `<td class="key-col small">${key[r.id] ? `${esc(key[r.id].expected.verdict)}${key[r.id].expected.verdict === r.verdict ? ' ✓' : ''}` : ''}</td>` : ''}
    <td><button data-replay-at="${r.id}:${r.asked}">Replay</button></td></tr>`).join('')}</table></div>`;
  return { html, mount() {
    if ($('#rv')) $('#rv').addEventListener('change', (ev) => { S.reveal = ev.target.checked; render(); });
    document.querySelectorAll('[data-replay-at]').forEach((b) => b.addEventListener('click', async () => {
      const [id, t] = b.dataset.replayAt.split(':').map(Number);
      await startReplay(id); setAsOf(t);
    }));
    const host = $('#learn'), L = d.learning;
    const series = ['both', 'symptom', 'part'].map((sig, k) => ({ box: sig, cls: `c${k + 1}`, points: L.map((x, i) => ({ t0: x.t, t1: i + 1 < L.length ? L[i + 1].t : d.t1, v: x[sig] })) }));
    const cfg = { t0: L[0].t, t1: Math.max(d.t1, L[L.length - 1].t), width: host.clientWidth, panels: [{ label: 'Starting confidence', unit: 'fraction', per_run: true, series }],
      rows: [], vlines: [{ t: L[0].t, cls: 'grid' }], aria: 'learned starting confidence per kind of match over time' };
    const chart = buildChart(cfg);
    host.innerHTML = chart.svg;
  } };
};

/* for developers --------------------------------------------------------------------- */
const READS = {
  entries: ['Entries whose event time overlaps a window.', ['elements', 'types', 'kinds', 'record_classes', 'sources', 'text', 't0', 't1', 'limit']],
  state_at: ['The last state of one type on an element at or before a time, however old.', ['element', 'type', 't']],
  incidents: ['All incidents, open and closed.', ['elements']],
  incident: ['One incident as the Record knew it.', ['incident_id']],
  incident_entries: ['The entries attached to an incident, with their roles.', ['incident_id']],
  links: ['Links touching an entry. Both ends must be known.', ['entry_id']],
  related: ['Service-side neighbours of an element: its supply, its FED, or the boxes it serves.', ['element']],
  subtree: ['An element and everything below it.', ['element']],
  ancestors: ['Everything above an element.', ['element']],
};
const HINT = { elements: 'HFP02,HF', types: 'lv_voltage_status', kinds: 'state,point', record_classes: 'MS,QA,HI', sources: 'dcs,elog', text: 'configure', t0: 'time', t1: 'time', t: 'time', limit: '50', element: 'HFP02', type: 'control_link', incident_id: '3', entry_id: '28' };
const RA = { method: 'state_at', values: {}, out: null };
PAGES.api = async () => {
  const [doc, args] = READS[RA.method];
  const html = `<h1>Read API</h1>
  <p class="muted">Run the Record's own read methods by hand. These are the calls every page here makes, and the calls the agent's tools will be built on. Every call that reads content takes <code>as_of</code>: the end of the Record normally, or the replay's moment during a replay.</p>
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
        if (r.result == null) body = '<p><b>None.</b> Nothing matches.</p>';
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


/* sortable tables: click a header to sort by that column, again to reverse ----------- */
function makeSortable(table) {
  const head = table.querySelector('tr');
  if (!head) return;
  [...head.children].forEach((th, col) => {
    th.classList.add('sorthead');
    th.title = 'Sort by this column';
    th.addEventListener('click', () => {
      const rows = [...table.querySelectorAll('tr')].slice(1);
      const dir = th.dataset.dir === 'asc' ? -1 : 1;
      head.querySelectorAll('th').forEach((h) => { delete h.dataset.dir; });
      th.dataset.dir = dir === 1 ? 'asc' : 'desc';
      const val = (tr) => { const td = tr.children[col]; return td ? (td.dataset.sort ?? td.textContent.trim()) : ''; };
      rows.sort((a, b) => {
        const x = val(a), y = val(b), nx = parseFloat(x), ny = parseFloat(y);
        const both = !Number.isNaN(nx) && !Number.isNaN(ny) && /^-?[\d.]/.test(x) && /^-?[\d.]/.test(y);
        return dir * (both ? nx - ny : x.localeCompare(y, undefined, { numeric: true }));
      });
      rows.forEach((tr) => tr.parentNode.appendChild(tr));
    });
  });
}

/* ----------------------------------------------------------------- shell */
let token = 0;
async function render() {
  const my = ++token;
  const parts = (location.hash.split('?')[0].replace(/^#\/?/, '') || 'detector').split('/');
  const page = PAGES[parts[0]] ? parts[0] : 'detector';
  drawNav(page);
  drawBar();
  const main = $('#main');
  try {
    const out = await PAGES[page](parts);
    if (my !== token) return;
    main.innerHTML = out.html;
    main.querySelectorAll('table.sortable').forEach(makeSortable);
    if (out.mount) out.mount();
  } catch (e) {
    if (my !== token) return;
    main.innerHTML = `<h1>Nothing to show</h1><p>${esc(e.message)}</p>` +
      (S.replay ? `<p class="muted">You are in a replay at ${tm(S.asOf)}. If this was learned later, step forward or leave the replay.</p>` : '');
  }
}
document.addEventListener('click', (ev) => {
  if (ev.target.closest('[data-recfile]')) { ev.stopPropagation(); openRecordPanel(); return; }
  const rp = ev.target.closest('[data-replay]');
  if (rp) { ev.stopPropagation(); startReplay(+rp.dataset.replay); return; }
  const fr = ev.target.closest('[data-free]');
  if (fr) { ev.stopPropagation(); startFreeReplay(+fr.dataset.free); return; }
  const a = ev.target.closest('[data-asof]');
  if (a) { ev.stopPropagation(); setAsOf(+a.dataset.asof); return; }
  const g = ev.target.closest('[data-go]');
  if (g && !ev.target.closest('a,button')) location.hash = g.dataset.go;
});
document.addEventListener('mousemove', (ev) => {
  const t = ev.target.closest && ev.target.closest('[data-tip]');
  if (t && t.dataset.tip) showTip(t.dataset.tip, ev);
  else if (!ev.target.closest || !ev.target.closest('#tl svg, #cal svg')) hideTip();
});
window.addEventListener('hashchange', () => { syncHash(); render(); window.scrollTo(0, 0); });
let resizeTimer = null;
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 200); });

/* which Record file is loaded ------------------------------------------------------- */
async function loadRecord() {
  S.meta = await api('meta', {}, false);
  S.asOf = S.meta.latest_known_at;
  S.elements = (await api('elements')).elements;
  $('#rec-name').textContent = S.meta.path;
}
async function openRecordPanel() {
  const panel = $('#rec-panel');
  if (!panel.hidden) { panel.hidden = true; return; }
  const d = await (await fetch('/api/records')).json();
  panel.innerHTML = `<b>Load a Record</b><p class="small muted">Record files found under ${esc(d.base)}. The GUI never writes to them.</p>
    <table>${d.records.map((r) => `<tr class="click${r.path === d.current ? ' on' : ''}" data-use="${esc(r.path)}"><td class="mono small">${esc(r.path.replace(d.base + '/', ''))}</td>
      <td>${esc(r.preset || '?')}, seed ${esc(r.seed || '?')}</td><td class="num">${r.entries} entries</td><td class="num">${r.size_mb} MB</td>
      <td class="small muted">${r.archive ? 'archive' : 'no archive'} · ${r.planted ? 'scenarios' : 'no scenarios'}</td></tr>`).join('')}</table>
    <div class="filters"><input type="text" id="rec-path" placeholder="or type a path to a .db file" size="46"><button id="rec-open" class="primary">Open</button></div>
    <p class="small muted">Build another with <code>pixi run orchestra synth --preset small --out out/small</code>.</p><p id="rec-err" class="small"></p>`;
  panel.hidden = false;
  const use = async (path) => {
    const r = await fetch('/api/use', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
    const j = await r.json();
    if (!r.ok) { $('#rec-err').textContent = j.error; return; }
    panel.hidden = true;
    stopPlay(); S.replay = null; S.planted = null; TB.incident = null; DV.mode = null; TL.t0 = null; RS.viewFor = null;
    Object.assign(RF, { cls: '', source: '', type: '', element: '', below: false, q: '', offset: 0 });
    await loadRecord(); location.hash = '#/detector'; syncHash(); render();
  };
  panel.querySelectorAll('[data-use]').forEach((row) => row.addEventListener('click', () => use(row.dataset.use)));
  $('#rec-open').addEventListener('click', () => use($('#rec-path').value));
}

(async function start() {
  S.meta = await api('meta', {}, false);
  $('#rec-name').textContent = S.meta.path;
  $('#rec-btn').addEventListener('click', openRecordPanel);
  $('#banner').title = S.meta.banner;
  S.asOf = S.meta.latest_known_at;
  S.elements = (await api('elements')).elements;
  const m = location.hash.match(/[?&]r=(\w+)&t=(\d+)/);
  if (m && m[1] !== 'free') {                      // a reloaded or shared replay link
    const d = await (await fetch(`/api/replay?id=${m[1]}&as_of=${S.meta.latest_known_at}`)).json();
    if (d.frame) { S.replay = { id: +m[1], title: d.frame.title, ask: d.ask_time, opened: d.frame.opened_at, steps: d.steps, prev: null }; S.asOf = +m[2]; }
  } else if (m) { S.replay = { id: null, title: null, ask: +m[2], opened: null, steps: null, prev: null }; S.asOf = +m[2]; }
  if (!location.hash) location.hash = '#/detector';
  render();
})();
