'use strict';
/* Operations Record browser.
   Every number shown comes from the local service, which calls the Record's own read
   methods. Normally the whole Record is shown. In a replay, every read is made "as of"
   the replay's moment and nothing later is shown. This file only draws. */

const S = { meta: null, asOf: 0, replay: null, elements: [], planted: null, reveal: false };
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
  if (e.type === 'lv_voltage' || e.type === 'temperature') return `mean ${p.mean} ${p.unit}, min ${p.min}, max ${p.max}, slope ${p.slope_per_h}/h`;
  if (e.type === 'downtime') return `${Math.floor(p.duration_s / 60)} min, ${p.lost_lumi_pb} /pb lost, ${p.category}: ${p.details}`;
  return Object.entries(p).map(([k, v]) => `${k}=${Array.isArray(v) ? JSON.stringify(v) : v}`).join(', ');
}
/* An empty label means "never recorded" normally, and "not known yet" during a replay. */
const empty = () => `<span class="unknown">${S.replay ? 'not known yet' : 'none recorded'}</span>`;
const entryLink = (id) => `<a href="#/entry/${id}">${id}</a>`;
const elLink = (name) => `<a href="#/timeline/${encodeURIComponent(name)}">${esc(name)}</a>`;
const incLink = (id, title) => `<a href="#/incident/${id}">#${id}${title ? ' ' + esc(title) : ''}</a>`;
const statusCell = (s) => `<span class="status">${s}</span>`;
const ENTRY_HEAD = '<th>Happened</th><th>Known to the Record</th><th class="num">id</th><th>Class</th><th>Source / type</th><th>Element</th><th>What</th>';
function entryRows(entries, extra) {
  return entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}">
    ${extra ? extra(e) : ''}<td class="t">${fmt(e.t_start)}</td><td class="t">${fmt(e.known_at)}</td>
    <td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td>
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
    <span>Every page shows the Record as it stood at <b>${fmt(S.asOf)}</b> UTC, and nothing learned later.</span>
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


/* --------------------------------------------------------- detector map */
const NORMAL = new Set(['on', 'ok', 'STABLE BEAMS', 'NO BEAM', 'TECHNICAL STOP']);
function mapSvg(d, width) {
  const W = Math.max(760, width), SW = 170, FW = 170, SX = 16, FX = W - FW - 16, BX = SX + SW + 70, BW = FX - 70 - BX, RH = 50, GAP = 10;
  const by = Object.fromEntries(d.elements.map((e) => [e.name, e]));
  const kids = (parent, kind) => d.elements.filter((e) => e.parent === parent && e.kind === kind);
  const rel = (e, r) => e.related.filter(([x]) => x === r).map(([, n]) => n);
  const hot = Object.fromEntries(d.flags.map((f) => [f.element, f]));
  const issues = {};
  for (const i of d.open_issues) (issues[i.element] = issues[i.element] || []).push(i);
  let y = 8, body = '', wires = '';
  const node = (e, x, yy, w, h, extra) => {
    const st = Object.entries(e.states);
    const bad = st.some(([, v]) => !NORMAL.has(v.value));
    const tip = [`${e.name} (${e.kind.replace('_', ' ')})`].concat(st.map(([k, v]) => `${k.replace('_', ' ')}: ${v.value} since ${fmt(v.since)}`),
      (issues[e.name] || []).map((i) => `open issue #${i.id}: ${i.title} (${i.status})`)).join('\n');
    let g = `<g class="hit" data-go="#/timeline/${encodeURIComponent(e.name)}" data-tip="${esc(tip)}">
      <rect x="${x}" y="${yy}" width="${w}" height="${h}" rx="6" class="node${bad ? ' bad' : ''}"/>
      <text class="title" x="${x + 10}" y="${yy + 18}">${esc(e.name)}</text>
      <text x="${x + 10}" y="${yy + 34}">${st.length ? st.map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v.value}`).join(' · ') : ''}</text>${extra || ''}</g>`;
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
          (issues[sub.name] || []).map((i) => `<text class="hit issue" x="${BX + 40}" y="${y + 14}" data-go="#/incident/${i.id}">open issue #${i.id}</text>`).join('');
        y += 22;
        for (const b of boxes) {
          const chans = kids(b.name, 'channel');
          const cw = Math.min(11, (BW - 150) / Math.max(1, chans.length));
          const cells = chans.map((c, k) => `<rect class="${hot[c.name] ? 'chan hot' : 'chan'}" x="${BX + 140 + k * cw}" y="${y + RH - 17}" width="${cw - 2}" height="9"><title>${esc(c.name)}${hot[c.name] ? ': flagged ' + hot[c.name].flag : ''}</title></rect>`).join('');
          const nhot = chans.filter((c) => hot[c.name]).length;
          body += node(b, BX, y, BW, RH - GAP, cells + `<text x="${BX + 140}" y="${y + 18}">${chans.length} channels${nhot ? `, ${nhot} flagged hot` : ''}</text>`);
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
    Object.entries(e.states).map(([k, v]) => ` · ${k.replace(/_/g, ' ')}: <b>${esc(v.value)}</b> since ${fmt(v.since)}`).join('') +
    d.open_issues.filter((i) => i.element === e.name).map((i) => ` · <a href="#/incident/${i.id}">open issue #${i.id}</a> (${i.status})`).join(''));
  return `<p>${bits.join('<br>')}</p>`;
}

/* --------------------------------------------------------------- tables */
const ER_POS = { element: [20, 20], element_relation: [20, 150], entry: [290, 20], link: [570, 20], incident_entry: [570, 250], incident: [290, 320], query_log: [830, 20], meta: [830, 180] };
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
  return `<svg viewBox="0 0 1060 590" width="1060" height="590" role="img" aria-label="the tables of the Record and how they point to each other">${boxes}${edges}</svg>`;
}
const TIME_COL = /(_at|^t_start|^t_end|^as_of)$/;
function rawTable(t, highlight) {
  if (!t.rows.length) return '<p class="muted">No rows at this time.</p>';
  const cell = (col, v) => {
    if (v == null) return '<span class="unknown">empty</span>';
    if (TIME_COL.test(col)) return `<span data-tip="stored as ${v} (seconds since 1970, UTC)">${fmt(v)}</span>`;
    const str = String(v);
    return str.length > 46 ? `<span data-tip="${esc(str)}">${esc(str.slice(0, 44))}…</span>` : esc(str);
  };
  return `<div class="tablewrap"><table class="raw"><tr>${t.columns.map((c) => `<th class="${highlight && highlight.includes(c) ? 'hl' : ''}">${c}</th>`).join('')}</tr>
    ${t.rows.map((r) => `<tr>${r.map((v, i) => `<td class="${highlight && highlight.includes(t.columns[i]) ? 'hl' : ''}">${cell(t.columns[i], v)}</td>`).join('')}</tr>`).join('')}</table></div>`;
}

const ROLE_CLASS = { symptom: 'c1', downtime: 'c2', action: 'c3', certification: 'c4', cause: 'c5', closing_note: 'c5', evidence: 'c7' };
const ROLE_LABEL = { symptom: 'symptom', downtime: 'downtime', action: 'action taken', certification: 'certification', cause: 'cause or closing note', evidence: 'evidence linked by an expert' };
function knowledgeChart(inc, entries, width, steps) {
  // Time is drawn relative to the start of the incident on a compressed scale, so minutes
  // and weeks fit on one axis: equal distance means ten times longer.
  const f = (dt) => Math.sign(dt) * Math.log10(1 + Math.abs(dt) / 60);
  const off = steps ? 44 : 0;
  const L = 118, R = 20, W = Math.max(520, width), yTop = 56 + off, yBot = 170 + off, H = 232 + off;
  const all = entries.flatMap((e) => [e.t_start - inc.t_start, e.known_at - inc.t_start]).concat(S.replay ? [S.asOf - inc.t_start, 0] : [0])
    .concat(steps ? steps.map((t) => t - inc.t_start) : []);
  const lo = f(Math.min(...all)) - 0.2, hi = f(Math.max(...all)) + 0.2;
  const X = (dt) => L + ((f(dt) - lo) / (hi - lo)) * (W - L - R);
  let s = `<text x="${L - 8}" y="${yTop + 4}" text-anchor="end">Happened</text><text x="${L - 8}" y="${yBot + 4}" text-anchor="end">Known</text>
    <line class="axis" x1="${L}" x2="${W - R}" y1="${yTop}" y2="${yTop}"/><line class="axis" x1="${L}" x2="${W - R}" y1="${yBot}" y2="${yBot}"/>`;
  const marks = [[-7 * 86400, '1 wk before'], [-86400, '1 d before'], [-6 * 3600, '6 h before'], [-3600, '1 h before'], [-600, '10 min before'], [0, 'start'],
    [600, '+10 min'], [3600, '+1 h'], [6 * 3600, '+6 h'], [86400, '+1 d'], [7 * 86400, '+1 wk'], [14 * 86400, '+2 wk'], [28 * 86400, '+4 wk']];
  for (const [dt, label] of marks) {
    if (f(dt) < lo || f(dt) > hi) continue;
    s += `<line class="grid" x1="${X(dt)}" x2="${X(dt)}" y1="${yTop - 14 - off}" y2="${yBot + 14}"/><text x="${X(dt)}" y="${yBot + 30}" text-anchor="middle">${label}</text>`;
  }
  if (S.replay) {
    const xn = X(S.asOf - inc.t_start);
    s += `<rect class="future" x="${xn}" y="${yTop - 14 - off}" width="${Math.max(0, W - R - xn)}" height="${yBot - yTop + 28 + off}"/>
      <line class="asof" x1="${xn}" x2="${xn}" y1="${yTop - 14 - off}" y2="${yBot + 14}"/>`;
  }
  if (steps) {
    const ys = yTop - off + 2;
    s += `<text x="${L - 8}" y="${ys + 4}" text-anchor="end">Steps</text><line class="axis" x1="${L}" x2="${W - R}" y1="${ys}" y2="${ys}"/>`;
    steps.forEach((t, k) => {
      const here = t === S.asOf, past = t <= S.asOf;
      s += `<circle class="hit step${here ? ' here' : past ? ' past' : ''}" cx="${X(t - inc.t_start)}" cy="${ys}" r="${here ? 8 : 5.5}" data-asof="${t}" data-tip="step ${k + 1}: ${fmt(t)}${past ? '' : '\n(later: click to go there)'}"/>`;
    });
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
  ['2', 'built', 'How the Record is built'],
  ['3', 'tables', 'What is in the Record', [['tables', 'Tables'], ['record', 'Entries'], ['incidents', 'Incidents'], ['timeline', 'Timeline']]],
  ['4', 'scenarios', 'Scenarios in this demo'],
  ['5', 'replay', 'Replay'],
];
const ALIAS = { entry: 'record', incident: 'incidents' };
function drawNav(current) {
  const cur = ALIAS[current] || current;
  $('#nav').innerHTML = NAV.map(([n, key, label, subs]) => {
    const on = cur === key || (subs && subs.some(([k]) => k === cur));
    return `<a href="#/${key}" class="navtop${on && !subs ? ' on' : ''}"><span class="n">${n}</span>${label}</a>` +
      (subs ? `<div class="subs">${subs.map(([k, l]) => `<a href="#/${k}" class="${cur === k ? 'on' : ''}">${l}</a>`).join('')}</div>` : '');
  }).join('') + '<div class="navfoot"><a href="#/api">For developers: read API</a></div>';
}

/* 1. the detector ------------------------------------------------------------------ */
PAGES.detector = async () => {
  const d = await api('map');
  const m = S.meta, n = (k) => d.elements.filter((e) => e.kind === k).length;
  const html = `<h1>The detector</h1>
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
    <tr><td>readout box</td><td class="num">${n('readout_box')}</td><td>On-detector electronics for a group of channels. Voltage, temperature and data-quality numbers are recorded per box.</td></tr>
    <tr><td>channel</td><td class="num">${n('channel')}</td><td>One readout channel. Only flagged when it misbehaves.</td></tr>
    <tr><td>low-voltage supply</td><td class="num">${n('lv_supply')}</td><td>Powers one or more boxes. Has a state: on, off or tripped.</td></tr>
    <tr><td>FED</td><td class="num">${n('fed')}</td><td>Back-end board that reads out one or more boxes.</td></tr></table></div>
  <h2>About this Record</h2>
  <dl class="facts card"><dt>File</dt><dd class="mono">${esc(m.path)} (${m.size_mb} MB, opened read-only)</dd>
    <dt>Generated with</dt><dd>preset <b>${esc(m.preset)}</b>, seed ${esc(m.seed)}</dd>
    <dt>Calendar</dt><dd>${fmt(m.t0)} to ${fmt(m.t1)} UTC</dd></dl>`;
  return { html, mount() { $('#map').innerHTML = mapSvg(d, $('#map').clientWidth); } };
};

/* 2. how the Record is built --------------------------------------------------------- */
PAGES.built = async () => {
  const d = await api('built');
  const ex = d.examples, win = d.config.ms_cadence_s / 60;
  const box = (name, what, state) => `<div class="box ${state}"><b>${name}</b>${what}</div>`;
  const row = (src, stage, e, demo) => `<tr><td>${src}</td><td>${stage}</td>
    <td class="mono small what">${e ? `${entryLink(e.id)} · ${esc(e.source)}/${esc(e.type)} · ${esc(e.element)}<br>${esc(JSON.stringify(e.payload))}` : 'none'}</td><td>${demo}</td></tr>`;
  const html = `<h1>How the Record is built</h1>
  <p class="lead">On a real detector a chain of software, the feed, builds the Record from existing systems. <b>Here that chain does not exist:</b> a generator writes finished entries straight into the Record.</p>
  <div class="pathlabel">As designed, for real records</div>
  <div class="flow">${box('Existing systems', 'controls, data quality, logbook, certification', 'off')}<span class="arrow">&#8594;</span>
    ${box('Adapters', 'read, map to parts', 'off')}<span class="arrow">&#8594;</span>${box('Anonymizer', 'names to roles', 'off')}<span class="arrow">&#8594;</span>
    ${box('Summarizer, sparsifier', 'shorten text, reduce readings', 'off')}<span class="arrow">&#8594;</span>${box('Aggregator', 'writes entries', 'real')}<span class="arrow">&#8594;</span>
    <a class="box real" href="#/tables"><b>The Record</b>${d.counts.entry} entries</a></div>
  <div class="pathlabel">In this demo</div>
  <div class="flow"><a class="box demo" style="flex:4 1 560px" href="#/scenarios"><b>Generator</b>invents a calendar, plants fault situations, writes everything</a><span class="arrow">&#8594;</span>
    ${box('Aggregator', 'the same code', 'real')}<span class="arrow">&#8594;</span><a class="box real" href="#/tables"><b>The Record</b>the same database</a></div>
  <div class="key"><span><i class="k-off"></i>dashed: not built</span><span><i class="k-real"></i>blue: runs here</span><span><i class="k-demo"></i>violet: demo only</span></div>

  <h2>Three sources, followed into the Record</h2>
  <div class="tablewrap"><table><tr><th>Source</th><th>What the feed would do</th><th>The entry in this Record</th><th>What the demo does instead</th></tr>
    ${row('<b>Voltage</b>, logged every few seconds', `Sparsifier: ${win}-minute windows, four numbers each`, ex.voltage, 'Formula plus noise; no raw series exists')}
    ${row('<b>Data-quality plots</b> per run', 'Sparsifier: a few numbers per run and box', ex.quality, 'Set from the planted faults; no plot exists')}
    ${row('<b>Logbook note</b>, free text with a name', 'Anonymizer: name to role. Summarizer: shorten', ex.note, 'A hand-written template; never any names')}
  </table></div>

  <h2>On top of entries</h2>
  <div class="tablewrap"><table>
    <tr><td><b>Direct link</b></td><td>Same part, same time. Built by code.</td></tr>
    <tr><td><b>Indirect link</b></td><td>An expert's reasoning: this supports that. Proposed by software, confirmed by an expert.</td></tr>
    <tr><td><b>Incident</b></td><td>Entries grouped into one problem, with recovery, cause and certification kept apart.${d.incident_example ? ` Example: ${incLink(d.incident_example.incident.id, d.incident_example.incident.title)}.` : ''}</td></tr>
  </table></div>
  <p class="muted small">In the demo the generator writes all links and incidents, already confirmed.</p>

  <h2>Choices the demo makes silently</h2>
  <p class="muted small">Each is a real design decision, not settled. Details are in docs/DESIGN.md, section 7a.</p>
  <div class="tablewrap"><table><tr><th>Choice</th><th>In the demo</th><th>What it hides</th></tr>
    <tr><td><b>Sparsifying readings</b></td><td>${win}-minute windows: mean, min, max, slope</td><td>Anything faster than a window; a size limit sets the window</td></tr>
    <tr><td><b>Summarizing data quality</b></td><td>Five numbers per run and box</td><td>Short problems are diluted; position is lost</td></tr>
    <tr><td><b>Plots</b></td><td>None</td><td>Intended: keep an incident's relevant plots, mostly logbook attachments</td></tr>
    <tr><td><b>When quality data arrive</b></td><td>Ten minutes after the run</td><td>Online plots are visible during a run</td></tr>
    <tr><td><b>Logbook text</b></td><td>One templated sentence</td><td>Real notes are long and irregular; matching is harder</td></tr>
    <tr><td><b>Which part a note is about</b></td><td>Known to the generator</td><td>Must be read from free text</td></tr>
    <tr><td><b>How late knowledge arrives</b></td><td>Fixed delays</td><td>Real delays vary; many causes are never written</td></tr>
    <tr><td><b>Complete incidents</b></td><td>Every fault has one</td><td>Only expert-reviewed incidents are this complete</td></tr>
    <tr><td><b>Language models</b></td><td>None used</td><td>The anonymizer and summarizer would use local ones</td></tr>
  </table></div>`;
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
  <h2>One incident, followed through the tables</h2>
  ${w ? `<div class="filters"><label>Incident <select id="tb-inc">${d.incidents.map((i) => `<option value="${i.id}"${i.id === d.incident_id ? ' selected' : ''}>#${i.id} ${esc(i.title)}</option>`).join('')}</select></label> <a href="#/incident/${d.incident_id}">open its page</a></div>
  <h3>1. One row in <span class="mono">incident</span></h3>${rawTable(w.incident, ['id', 'element_id'])}
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

const RF = { cls: '', source: '', type: '', kind: '', element: '', below: false, q: '', order: 'oldest', offset: 0 };
PAGES.record = async () => {
  const o = await api('overview');
  const params = { limit: 100, offset: RF.offset, order: RF.order };
  if (RF.cls) params.class = RF.cls; if (RF.source) params.source = RF.source; if (RF.type) params.type = RF.type;
  if (RF.kind) params.kind = RF.kind; if (RF.q) params.q = RF.q;
  if (RF.element) { params.element = RF.element; if (RF.below) params.below = 1; }
  const d = await api('entries', params);
  const uniq = (i) => [...new Set(o.entries_by_type.map((r) => r[i]))].sort();
  const sel = (key, label, values) => `<label>${label} <select data-rf="${key}"><option value="">all</option>${values.map((v) => `<option${RF[key] === v ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  const names = { MS: 'machine state', QA: 'quality', HI: 'human' };
  const html = `<h1>What is in the Record: entries</h1>
  <p class="lead">Every reading summary, event, note and flag is one entry. Click a row for the full entry.</p>
  <details><summary>What kinds of entry there are (${o.entries_by_type.length} types, ${o.n_entries} entries)</summary>
  <div class="tablewrap"><table><tr><th>Class</th><th>Source</th><th>Type</th><th>Kind</th><th class="num">Entries</th></tr>
  ${o.entries_by_type.map(([c, s, t, k, n]) => `<tr class="click" data-filter='${JSON.stringify({ cls: c, source: s, type: t })}'><td>${c} <span class="muted">${names[c]}</span></td><td>${esc(s)}</td><td>${esc(t)}</td><td>${k}</td><td class="num">${n}</td></tr>`).join('')}</table></div></details>
  <div class="filters">
    ${sel('cls', 'Class', uniq(0))}${sel('source', 'Source', uniq(1))}${sel('type', 'Type', uniq(2))}${sel('kind', 'Kind', uniq(3))}
    ${sel('element', 'Element', S.elements.map((e) => e.name))}
    <label><input type="checkbox" data-rf="below"${RF.below ? ' checked' : ''}> and everything below it</label>
    <label>Text <input type="text" data-rf="q" value="${esc(RF.q)}" placeholder="search the content"></label>
    <label>Order <select data-rf="order"><option value="oldest"${RF.order === 'oldest' ? ' selected' : ''}>oldest first</option><option value="newest"${RF.order === 'newest' ? ' selected' : ''}>newest first</option></select></label>
    <button data-rf-clear>Clear</button>
  </div>
  <div class="pager"><b>${d.total}</b> entries match. Showing ${d.total ? RF.offset + 1 : 0} to ${RF.offset + d.entries.length}.
    <button data-rf-page="-100"${RF.offset ? '' : ' disabled'}>&#9664; previous</button><button data-rf-page="100"${RF.offset + 100 < d.total ? '' : ' disabled'}>next &#9654;</button></div>
  <div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows(d.entries)}</table></div>`;
  return { html, mount() {
    document.querySelectorAll('[data-rf]').forEach((el) => el.addEventListener('change', () => { RF[el.dataset.rf] = el.type === 'checkbox' ? el.checked : el.value; RF.offset = 0; render(); }));
    $('[data-rf-clear]').addEventListener('click', () => { Object.assign(RF, { cls: '', source: '', type: '', kind: '', element: '', below: false, q: '', offset: 0 }); render(); });
    document.querySelectorAll('[data-rf-page]').forEach((b) => b.addEventListener('click', () => { RF.offset = Math.max(0, RF.offset + (+b.dataset.rfPage)); render(); }));
    document.querySelectorAll('[data-filter]').forEach((r) => r.addEventListener('click', () => { Object.assign(RF, { cls: '', source: '', type: '', kind: '', element: '', q: '', offset: 0 }, JSON.parse(r.dataset.filter)); render(); }));
  } };
};

PAGES.entry = async (parts) => {
  const d = await api('entry', { id: parts[1] });
  const e = d.entry;
  const html = `<h1>Entry ${e.id}</h1><p class="lead">${esc(describe(e))}</p>
  <div class="cols"><div class="card"><dl class="facts">
    <dt>Class</dt><dd>${e.record_class}</dd><dt>Source / type</dt><dd>${esc(e.source)} / ${esc(e.type)}</dd><dt>Kind</dt><dd>${e.kind}</dd>
    <dt>Element</dt><dd>${d.element_path.map(elLink).join(' &lsaquo; ')}</dd>
    <dt>Happened</dt><dd>${fmt(e.t_start)}${e.t_end ? ' to ' + fmt(e.t_end) : ''}</dd>
    <dt>Known to the Record</dt><dd>${fmt(e.known_at)} <span class="muted">(${dur(e.known_at - e.t_start)} after it started)</span></dd>
    <dt>Written by</dt><dd class="mono">${esc(e.producer)} ${esc(e.producer_version)}</dd>
    <dt>Source pointer</dt><dd class="mono">${esc(e.raw_ref)}</dd>
    <dt>Review status</dt><dd>${e.review_status}</dd>
    <dt>Corrects</dt><dd>${e.supersedes ? entryLink(e.supersedes) : 'nothing'}</dd>
    <dt>Corrected by</dt><dd>${d.superseded_by ? entryLink(d.superseded_by) : 'nothing'}</dd>
  </dl></div><div class="card"><b>Content (payload)</b><pre>${esc(JSON.stringify(e.payload, null, 2))}</pre></div></div>
  <h2>Incidents this entry belongs to</h2>
  ${d.incidents.length ? '<ul>' + d.incidents.map((i) => `<li>${incLink(i.id, i.title)} as <b>${esc(i.role)}</b></li>`).join('') + '</ul>' : '<p class="muted">None.</p>'}
  <h2>Links</h2>
  ${d.links.length ? `<div class="tablewrap"><table><tr><th>Link</th><th>Other entry</th><th>What it is</th><th>Reason given</th><th>Known</th></tr>${d.links.map((l) =>
    `<tr><td>${l.link_type}<br>${l.direction === 'out' ? 'this ' + esc(l.relation) + ' &#8594;' : '&#8592; ' + esc(l.relation) + ' this'}</td>
     <td>${entryLink(l.other.id)}</td><td class="what">${esc(describe(l.other))}</td><td class="what">${esc(l.rationale)}</td><td class="t">${fmt(l.known_at)}</td></tr>`).join('')}</table></div>` : '<p class="muted">None.</p>'}`;
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
  ${d.incidents.map((i) => `<tr class="click" data-go="#/incident/${i.id}"><td class="num">${i.id}</td><td class="t">${fmt(i.t_start)}</td><td>${statusCell(i.status)}</td><td>${esc(i.element)}</td><td>${esc(i.title)}</td>
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
    <dt>Started</dt><dd>${fmt(i.t_start)}</dd>
    <dt>Ended</dt><dd>${i.t_end ? fmt(i.t_end) + ` <span class="muted">(${dur(i.t_end - i.t_start)})</span>` : empty()}</dd>
    <dt>Recovery action</dt><dd>${i.recovery_action ? esc(i.recovery_action) : empty()}</dd>
    <dt>Confirmed cause</dt><dd>${i.confirmed_cause ? esc(i.confirmed_cause) : empty()}</dd>
    <dt>Certification</dt><dd>${i.certification ? esc(i.certification) : empty()}</dd>
  </dl></div>
  <div class="filters">${S.replay && S.replay.id === i.id ? '<a href="#/replay">Back to the replay</a>' : `<button class="primary" data-replay="${i.id}">Replay this incident</button> <span class="muted small">step through how the Record learned about it</span>`}
    · <a href="#/timeline/${encodeURIComponent(i.element)}">Timeline of ${esc(i.element)}</a></div>
  <h2>When each piece happened, and when the Record learned of it</h2>
  <p class="muted small">Each entry is drawn twice: when it happened (top) and when it became known (bottom). A vertical line was known at once; a long slanted line was written much later. The scale is compressed: each step to the right is about ten times longer.</p>
  <div class="key">${roles.map((r) => `<span><i class="${ROLE_CLASS[r]}"></i>${ROLE_LABEL[r] || r}</span>`).join('')}</div>
  <div id="know"></div>
  <h2>Entries attached (${d.entries.length})</h2>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}<th>Delay</th></tr>${d.entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}"><td>${esc(e.role)}</td>
    <td class="t">${fmt(e.t_start)}</td><td class="t">${fmt(e.known_at)}</td><td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td><td class="what">${esc(describe(e))}</td><td class="t">${dur(e.known_at - e.t_start)}</td></tr>`).join('')}</table></div>
  <h2>Expert reasoning</h2>
  ${expert.length ? '<ul>' + expert.map((l) => `<li>entry ${entryLink(l.src_entry_id)} ${esc(l.relation)} entry ${entryLink(l.dst_entry_id)}: ${esc(l.rationale)} <span class="muted small">(recorded ${fmt(l.known_at)})</span></li>`).join('') + '</ul>' : `<p class="muted">No expert links ${S.replay ? 'yet' : 'recorded'}.</p>`}`;
  return { html, mount() { $('#know').innerHTML = knowledgeChart(i, d.entries, $('#know').clientWidth); } };
};

const TL = { t0: null, t1: null, typical: false };
PAGES.timeline = async (parts) => {
  const name = parts[1] ? decodeURIComponent(parts[1]) : (S.elements.find((e) => e.kind === 'readout_box') || S.elements[0]).name;
  const d = await api('timeline', { element: name });
  if (TL.t0 == null) { TL.t0 = d.t0; TL.t1 = d.t1; }
  const kinds = ['subdetector', 'readout_box', 'lv_supply', 'fed', 'detector'];
  const html = `<h1>What is in the Record: timeline of ${esc(name)}</h1>
  <p class="lead">Readings from ${d.boxes.map(esc).join(', ')}${d.n_boxes > d.boxes.length ? ` (first ${d.boxes.length} of ${d.n_boxes} boxes)` : ''}, with what was recorded about ${esc(name)} and the parts around it.</p>
  <div class="filters">
    <label>Element <select id="tl-el">${kinds.map((k) => `<optgroup label="${k.replace('_', ' ')}">${S.elements.filter((e) => e.kind === k).map((e) => `<option${e.name === name ? ' selected' : ''}>${esc(e.name)}</option>`).join('')}</optgroup>`).join('')}</select></label>
    <button data-tl="in">Zoom in</button><button data-tl="out">Zoom out</button><button data-tl="left">&#9664;</button><button data-tl="right">&#9654;</button>
    <button data-tl="all">Whole calendar</button>
    <label><input type="checkbox" id="tl-typ"${TL.typical ? ' checked' : ''}> Vertical scale: typical range</label>
  </div>
  ${d.boxes.length > 1 ? `<div class="key">${d.boxes.map((b, k) => `<span><i class="c${k + 1}"></i>${esc(b)}</span>`).join('')}</div>` : ''}
  <div id="tl"></div>
  <details open><summary>How to read this</summary>
  <ul><li><b>Each point is one entry.</b> A voltage or temperature point summarizes one window: the line is the mean, and the light band (shown for a single box) is the minimum to maximum within that window. The band is not an uncertainty. <a href="#/built">Why only a few numbers per window.</a></li>
  <li>Dead channels, hot channels and occupancy are one entry per run, drawn as a flat segment across the run.</li>
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
function mountTimeline(host, d, view, name) {
  const rows = d.strip.map((r) => ({ label: r.row, items: r.items.map((it) => ({
    t0: it.t0, ...(r.row === 'Stable beams' || r.row === 'Downtime' || r.row === 'Certified bad' ? { t1: it.t1 ?? null } : {}),
    cls: { 'Stable beams': 'beam', Downtime: 'down', 'Certified bad': 'bad', 'State change': 'mk', 'Fault event': it.planned ? 'mk' : 'mk crit', 'Logbook note': it.routine ? 'note routine' : 'note' }[r.row],
    shape: { 'State change': 'diamond', 'Fault event': 'tri', 'Logbook note': 'tick' }[r.row],
    tip: `${fmt(it.t0)}\n${it.text}`, go: `#/entry/${it.id}` })) }));
  const draw = () => {
    const cfg = { t0: view.t0, t1: view.t1, width: host.clientWidth, typical: view.typical, panels: d.panels, rows,
      vlines: d.incidents.map((i) => ({ t: i.t_start, cls: 'inc', label: `#${i.id}`, tip: `${i.title} (${i.status})`, go: `#/incident/${i.id}` })).concat(S.replay ? [{ t: S.asOf, cls: 'asof' }] : []),
      aria: `readings and recorded events for ${name}` };
    const chart = buildChart(cfg);
    host.innerHTML = chart.svg;
    wireChart(host, chart, cfg, { zoom: (a, b) => { view.t0 = a; view.t1 = b; draw(); }, reset: () => { view.t0 = d.t0; view.t1 = d.t1; draw(); } });
  };
  draw();
  return draw;
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
  const html = `<h1>Scenarios in this demo</h1>
  <p class="lead">The generator planted ${d.cases.length} situations into the routine background. They are the worked examples of this demo. A real Record has no such list: this page reads the generator's own notes, kept in a separate file, not the Record.</p>
  <div class="tabs">${modes.map((m) => `<button data-dv-mode="${m}" class="${m === DV.mode ? 'on' : ''}">${esc(d.modes[m].title)} (${d.cases.filter((x) => x.mode === m).length})</button>`).join('')}</div>
  <div class="note"><b>${esc(d.modes[DV.mode].title)}.</b> ${esc(d.modes[DV.mode].story)}</div>
  ${cases.length > 1 ? `<div class="tabs">${cases.map((x, k) => `<button data-dv-idx="${k}" class="${x.id === c.id ? 'on' : ''}">${esc(x.true_element)} · ${fmtShort(x.t_event)}</button>`).join('')}</div>` : ''}
  <div class="card"><dl class="facts">
    <dt>Where the fault really is</dt><dd>${elLink(c.true_element)}</dd><dt>Where the crew sees it</dt><dd>${esc(c.reported_element)}</dd>
    <dt>Starts</dt><dd>${fmt(c.t_event)}</dd>
    <dt>In the Record as</dt><dd>${c.incident ? incLink(c.incident.id, c.incident.title) + ` <button data-replay="${c.incident.id}">Replay</button>` : `no incident, because nothing is wrong <button data-free="${c.ask_at}">look at the Record at that moment</button>`}</dd>
  </dl></div>
  <h2>What the generator wrote for it</h2>
  <p class="muted small">Compare "happened" with "known": the gap is how late that piece reaches the Record.</p>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}<th>Delay</th></tr>${c.entries.map((e) => `<tr class="click" data-go="#/entry/${e.id}"><td>${esc(e.role)}</td>
    <td class="t">${fmt(e.t_start)}</td><td class="t">${fmt(e.known_at)}</td><td class="num">${e.id}</td><td>${e.record_class}</td><td>${esc(e.source)}/${esc(e.type)}</td><td>${esc(e.element)}</td><td class="what">${esc(describe(e))}</td><td class="t">${dur(e.known_at - e.t_start)}</td></tr>`).join('')}</table></div>`;
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
    <dt>Crew's question</dt><dd>${esc(caseFor.question)} <span class="muted">(asked at ${fmt(caseFor.ask_at)})</span></dd>
    <dt>Honest answer at that moment</dt><dd><b>${esc(x.verdict.replace(/_/g, ' '))}</b>; next step: ${esc(x.next_step.replace(/_/g, ' '))}${x.precedents.length ? '; seen before as ' + x.precedents.map((p) => '#' + p).join(' ') : ''}</dd></dl>`;
}
const precTable = (rows) => rows.length ? `<div class="tablewrap"><table><tr><th>#</th><th>Started</th><th>Element</th><th>Title</th><th>Status then</th><th>Recovery known then</th><th>Cause known then</th></tr>
  ${rows.map((r) => `<tr class="click" data-go="#/incident/${r.id}"><td class="num">${r.id}</td><td class="t">${fmt(r.t_start)}</td><td>${esc(r.element)}</td><td>${esc(r.title)}</td><td>${statusCell(r.status)}</td>
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
    <p class="muted small">"Seen before?" asks, at the moment a crew would first ask, whether an earlier incident was already on record. Two possible rules are shown: an earlier incident on the same element, or one with the same kind of symptom on any element.</p>
    <div class="filters">${pl ? reveal : ''}</div>
    <div class="tablewrap"><table><tr><th></th><th>#</th><th>Started</th><th>Element</th><th>Title</th><th>Seen before on the same element?</th><th>Seen before with the same symptom?</th>${S.reveal ? '<th class="key-col">Planted situation</th><th class="key-col">Honest answer when asked</th>' : ''}</tr>
    ${d.incidents.map((i) => `<tr><td><button class="primary" data-replay="${i.id}">Replay</button></td><td class="num">${i.id}</td><td class="t">${fmt(i.t_start)}</td><td>${esc(i.element)}</td><td>${incLink(i.id, i.title)}</td>
      <td>${list(i.same_element)}</td><td>${list(i.same_symptom)}</td>${S.reveal ? `<td class="key-col">${cases[i.id] ? esc(cases[i.id].mode.replace(/_/g, ' ')) : ''}</td><td class="key-col">${cases[i.id] ? esc(cases[i.id].expected.verdict.replace(/_/g, ' ')) + ', ' + esc(cases[i.id].expected.next_step.replace(/_/g, ' ')) : ''}</td>` : ''}</tr>`).join('')}</table></div>
    <p>Across these ${d.incidents.length} incidents, the same-element rule says "seen before" for <b>${d.known_by_same_element}</b>, the same-symptom rule for <b>${d.known_by_same_symptom}</b>, and they disagree on <b>${d.disagree}</b>.</p>
    ${S.reveal && others.length ? `<h2>Planted situations that are not incidents</h2><ul>${others.map((c) => `<li>${esc(c.mode.replace(/_/g, ' '))} on ${esc(c.true_element)} at ${fmt(c.t_event)}: the honest answer is "${esc(c.expected.verdict.replace(/_/g, ' '))}". <button data-free="${c.ask_at}">Look at the Record when the crew asks</button></li>`).join('')}</ul>` : ''}`;
    return { html, mount() { if ($('#rv')) $('#rv').addEventListener('change', (ev) => { S.reveal = ev.target.checked; render(); }); } };
  }
  if (r.id == null) {
    const d = r.prev != null && r.prev < S.asOf ? await api('diff', { since: r.prev }) : null;
    const html = `<h1>The Record at ${fmt(S.asOf)}</h1>
    <p class="lead">A past moment, without following a particular incident. A step is the next moment the Record learned anything.</p>
    ${stepControls()}
    ${replaySections(null)}
    ${d ? `<h2>Learned in the last step</h2><p>${d.n_entries} entries, ${d.n_links} links, ${d.incident_changes.length} incident changes since ${fmt(d.from)}.</p>
      ${d.incident_changes.length ? '<ul>' + d.incident_changes.map((c) => `<li>${fmt(c.t)} · ${incLink(c.incident_id, c.title)}: ${esc(c.what)}</li>`).join('') + '</ul>' : ''}
      <div class="tablewrap"><table><tr>${ENTRY_HEAD}</tr>${entryRows(d.entries)}</table></div>` : ''}`;
    return { html, mount() { wireSteps(); mountReplaySections(null); } };
  }
  const d = await api('replay', r.prev != null && r.prev < S.asOf ? { id: r.id, since: r.prev } : { id: r.id });
  const i = d.incident, f = d.frame, p = d.precedents;
  const caseFor = pl ? pl.cases.find((c) => c.incident_id === r.id) : null;
  const roles = [...new Set(d.entries.filter((e) => e.role).map((e) => (e.role === 'closing_note' ? 'cause' : e.role)))];
  const html = `<h1>Replay of incident #${f.id}: ${esc(f.title)}</h1>
  <p class="lead">The problem starts at ${fmt(f.t_start)}. You are at <b>${fmt(S.asOf)}</b>, ${dur(Math.abs(S.asOf - f.t_start))} ${S.asOf >= f.t_start ? 'after' : 'before'} the start.</p>
  ${stepControls()}
  <h2>How knowledge has arrived so far</h2>
  <p class="muted small">Top row: each step is a moment the Record learned something about this incident; click one to go there. Below, each entry is drawn when it happened and when it became known. The shaded part is still in the future. The scale is compressed: each step to the right is about ten times longer.</p>
  <div class="key"><span><i class="c0"></i>a symptom on record, not yet linked to an incident</span>${roles.map((x) => `<span><i class="${ROLE_CLASS[x]}"></i>${ROLE_LABEL[x] || x}</span>`).join('')}</div>
  <div id="know"></div>
  <div class="cols"><div class="card"><b>What the Record says about this problem now</b>
    ${i ? `<dl class="facts"><dt>Status</dt><dd>${statusCell(i.status)}</dd><dt>Recovery action</dt><dd>${i.recovery_action ? esc(i.recovery_action) : empty()}</dd>
      <dt>Confirmed cause</dt><dd>${i.confirmed_cause ? esc(i.confirmed_cause) : empty()}</dd><dt>Certification</dt><dd>${i.certification ? esc(i.certification) : empty()}</dd></dl>`
      : `<p>Nothing yet as an incident. ${d.entries.length} symptom entries are on record, but nobody has grouped them: the incident is opened at ${fmt(f.opened_at)}.</p>`}</div>
  <div class="card"><b>Learned in the last step</b>
    ${d.learned ? ((d.learned.changes.length || d.learned.entries.length) ? '<ul>' + d.learned.changes.map((c) => `<li>${esc(c.what)}</li>`).join('') + d.learned.entries.map((e) => `<li>entry ${entryLink(e.id)}: ${esc(describe(e))}</li>`).join('') + '</ul>' : '<p class="muted">Entries already on record were attached to the incident.</p>') : '<p class="muted">Press "next step".</p>'}</div></div>
  ${replaySections(f.element)}
  <details ${RS.seen ? 'open' : ''} data-rs="seen"><summary><b>Has this been seen before?</b> ${p.same_element.length} on the same element, ${p.same_symptom.length} with the same kind of symptom</summary>
  <p class="muted small">Earlier incidents on record at this moment, as the Record knew them now. Symptom kinds of this problem so far: <span class="mono">${p.symptom_kinds.map(esc).join(', ') || 'none on record yet'}</span>.</p>
  <h3>On the same element (${p.same_element.length})</h3>${precTable(p.same_element)}
  <h3>With the same kind of symptom, on any element (${p.same_symptom.length})</h3>${precTable(p.same_symptom)}</details>
  <details ${RS.entries ? 'open' : ''} data-rs="entries"><summary><b>Entries on record for this problem</b> (${d.entries.length})</summary>
  <p class="muted small">Before the incident is opened, only its symptoms are listed: they are what the crew is looking at. Evidence that an expert links later appears when that link is recorded, not before.</p>
  <div class="tablewrap"><table><tr><th>Role</th>${ENTRY_HEAD}</tr>${entryRows(d.entries, (e) => `<td>${e.role ? esc(e.role) : '<span class="unknown">not yet linked</span>'}</td>`)}</table></div></details>
  ${pl ? `<details ${S.reveal ? 'open' : ''} id="rvd"><summary><b>Answer key</b> <span class="muted small">the generator's own notes, never part of the Record</span></summary><div class="note keynote">${answerKey(caseFor)}</div></details>` : ''}`;
  return { html, mount() {
    wireSteps();
    $('#know').innerHTML = knowledgeChart({ t_start: f.t_start }, d.entries, $('#know').clientWidth, r.steps);
    if ($('#rvd')) $('#rvd').addEventListener('toggle', (ev) => { S.reveal = ev.target.open; });
    mountReplaySections(f.element);
  } };
};
/* Collapsible views inside the replay page. They are the same drawings as the full pages,
   fed with the same as-of data. */
const RS = { map: false, tl: false, seen: true, entries: false, view: null, viewFor: null };
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
const HINT = { elements: 'HFP02,HF', types: 'lv_voltage', kinds: 'state,point', record_classes: 'MS,QA,HI', sources: 'dcs,elog', text: 'configure', t0: 'time', t1: 'time', t: 'time', limit: '50', element: 'HFP02', type: 'control_link', incident_id: '3', entry_id: '28' };
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
    if (out.mount) out.mount();
  } catch (e) {
    if (my !== token) return;
    main.innerHTML = `<h1>Nothing to show</h1><p>${esc(e.message)}</p>` +
      (S.replay ? `<p class="muted">You are in a replay at ${fmt(S.asOf)}. If this was learned later, step forward or leave the replay.</p>` : '');
  }
}
document.addEventListener('click', (ev) => {
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

(async function start() {
  S.meta = await api('meta', {}, false);
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
