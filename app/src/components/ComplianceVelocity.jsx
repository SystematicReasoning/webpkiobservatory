import React, { useMemo, useState } from 'react';
import { usePipeline } from '../PipelineContext';
import { Card, CardTitle } from './shared';

const C = {
  bg: 'var(--bg)', tx: 'var(--tx)', t2: 'var(--t2)', t3: 'var(--t3)', bd: 'var(--bd)',
};

const DOC_META = {
  tls_br:   { label: 'TLS BR',        color: '#1a9641' },
  ev_g:     { label: 'EV Guidelines', color: '#52be80' },
  ns_reqs:  { label: 'NS Reqs',       color: '#17a589' },
  smime_br: { label: 'S/MIME BR',     color: '#e6550d' },
  cs_br:    { label: 'CS BR',         color: '#d4a017' },
};

// Match revision table entries to version_history obligation counts
// by finding the closest computed entry within 60 days of the ballot date
function matchObligation(ballotDate, versionHistory) {
  if (!versionHistory?.length) return null;
  const bd = new Date(ballotDate).getTime();
  let best = null, bestDiff = Infinity;
  for (const v of versionHistory) {
    const diff = Math.abs(new Date(v.date).getTime() - bd);
    if (diff < bestDiff && diff < 60 * 86400000) {
      bestDiff = diff;
      best = v;
    }
  }
  return best;
}

export default function ComplianceVelocity({ complianceData: propData }) {
  const ctx = usePipeline();
  const data = propData || ctx?.complianceData;
  const [hover, setHover] = useState(null);
  const [focusDoc, setFocusDoc] = useState(null);

  const vh = data?.version_history || {};
  const revHistory = data?.revision_history || {};

  if (!Object.keys(revHistory).length && !Object.keys(vh).length) return null;

  const W = 700, H = 300;
  const PAD = { l: 52, r: 20, t: 24, b: 44 };
  const chartW = W - PAD.l - PAD.r;
  const chartH = H - PAD.t - PAD.b;

  // Build unified timeline: revision table entries enriched with obligation counts
  const docTimelines = useMemo(() => {
    const result = {};
    for (const [doc, meta] of Object.entries(DOC_META)) {
      const revEntries = revHistory[doc] || [];
      const vhEntries = vh[doc] || [];

      // If we have revision table data, use it as the backbone
      // Enrich with obligation counts where we can match dates
      let timeline;
      if (revEntries.length > 0) {
        let lastKnownTotal = null;
        timeline = revEntries.map(e => {
          const matched = matchObligation(e.date, vhEntries);
          if (matched) lastKnownTotal = matched.total;
          return {
            date: e.date,
            version: e.version,
            ballot: e.ballot,
            desc: e.desc,
            total: matched?.total ?? null,
            lastKnown: lastKnownTotal,
            computed: !!matched,
            source: matched ? 'computed' : 'table_only',
          };
        });
        // Forward-fill lastKnown so we can draw a continuous step line
        let fill = null;
        for (const e of timeline) {
          if (e.total !== null) fill = e.total;
          e.lastKnown = fill;
        }
      } else {
        // Fall back to version_history only
        timeline = vhEntries.map(v => ({
          date: v.date,
          version: v.tag,
          ballot: v.tag,
          desc: v.desc || '',
          total: v.total,
          lastKnown: v.total,
          computed: true,
          source: 'computed',
        }));
      }

      if (timeline.length > 0) result[doc] = { meta, timeline };
    }
    return result;
  }, [vh, revHistory]);

  const minDate = new Date('2011-06-01').getTime();
  const maxDate = new Date('2026-09-01').getTime();

  // Max total across all docs with known values
  const allTotals = Object.values(docTimelines).flatMap(d =>
    d.timeline.filter(e => e.lastKnown !== null).map(e => e.lastKnown)
  );
  const maxTotal = Math.max(...allTotals, 1400);

  const xScale = d => PAD.l + ((new Date(d).getTime() - minDate) / (maxDate - minDate)) * chartW;
  const yScale = t => PAD.t + chartH - (t / maxTotal) * chartH;

  const xTicks = [2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026];
  const yTicks = [0, 250, 500, 750, 1000, 1250];

  const isActive = doc => !focusDoc || focusDoc === doc;

  // Build step-function path from timeline entries that have known totals
  function buildStepPath(timeline) {
    const pts = timeline.filter(e => e.lastKnown !== null);
    if (pts.length === 0) return '';
    return pts.reduce((acc, p, i) => {
      const x = xScale(p.date).toFixed(1);
      const y = yScale(p.lastKnown).toFixed(1);
      if (i === 0) return `M${x},${y}`;
      return `${acc} H${x} V${y}`;
    }, '');
  }

  return (
    <Card>
      <CardTitle sub="Each tick = one ballot. Solid line = computed obligation count. Dashed = extrapolated. Hover for ballot details.">
        Ballot Velocity — {Object.values(docTimelines).reduce((s, d) => s + d.timeline.length, 0)} ballots across {Object.keys(docTimelines).length} documents, 2012–2026
      </CardTitle>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible', display: 'block' }}>
        {/* Grid */}
        {yTicks.map(v => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={yScale(v)} y2={yScale(v)}
              stroke={C.bd} strokeOpacity={0.5} strokeDasharray="3 3" />
            <text x={PAD.l - 5} y={yScale(v) + 3} textAnchor="end" fontSize={8} fill={C.t3}>
              {v >= 1000 ? `${v/1000}k` : v}
            </text>
          </g>
        ))}
        {xTicks.map(y => (
          <g key={y}>
            <line x1={xScale(`${y}-01-01`)} x2={xScale(`${y}-01-01`)}
              y1={PAD.t} y2={PAD.t + chartH}
              stroke={C.bd} strokeOpacity={0.35} strokeDasharray="3 3" />
            <text x={xScale(`${y}-01-01`)} y={PAD.t + chartH + 12}
              textAnchor="middle" fontSize={8} fill={C.t3}>{y}</text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={PAD.t + chartH} y2={PAD.t + chartH} stroke={C.bd} />
        <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + chartH} stroke={C.bd} />

        {/* Document trajectories */}
        {Object.entries(docTimelines).map(([doc, { meta, timeline }]) => {
          const op = isActive(doc) ? 1 : 0.1;
          const stepPath = buildStepPath(timeline);

          // Find segments with computed values vs extrapolated
          const computedPts = timeline.filter(e => e.computed && e.total !== null);
          const tablePts = timeline.filter(e => !e.computed);

          return (
            <g key={doc} style={{ opacity: op }}>
              {/* Step line through computed points */}
              {stepPath && (
                <path d={stepPath} fill="none" stroke={meta.color}
                  strokeWidth={1.8} strokeLinejoin="round" />
              )}

              {/* Table-only ballot ticks (rug at bottom of chart) */}
              {tablePts.map(p => (
                <line key={p.date + p.ballot}
                  x1={xScale(p.date)} x2={xScale(p.date)}
                  y1={PAD.t + chartH + 2} y2={PAD.t + chartH + 7}
                  stroke={meta.color} strokeWidth={1.2} strokeOpacity={0.6}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setHover({ ...p, meta, cx: xScale(p.date), cy: PAD.t + chartH + 4 })}
                  onMouseLeave={() => setHover(null)}
                />
              ))}

              {/* Computed points — dots sized by delta */}
              {computedPts.map((p, i) => {
                const prev = computedPts[i - 1];
                const delta = prev ? p.total - prev.total : 0;
                const r = Math.max(2.5, Math.min(8, Math.abs(delta) / 30));
                return (
                  <circle key={p.date + p.ballot}
                    cx={xScale(p.date)} cy={yScale(p.total)}
                    r={r}
                    fill={meta.color} stroke={C.bg} strokeWidth={0.8}
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={() => setHover({
                      ...p, meta, delta,
                      cx: xScale(p.date), cy: yScale(p.total)
                    })}
                    onMouseLeave={() => setHover(null)}
                  />
                );
              })}
            </g>
          );
        })}

        {/* Hover tooltip */}
        {hover && (() => {
          const TW = 190, TH = hover.total !== null ? 70 : 55;
          const tx = hover.cx > W * 0.65 ? hover.cx - TW - 6 : hover.cx + 8;
          const ty = hover.cy < PAD.t + 50 ? hover.cy + 8 : hover.cy - TH - 6;
          const isRug = hover.cy > PAD.t + chartH;
          return (
            <g>
              <rect x={tx} y={ty} width={TW} height={TH}
                fill={C.bg} stroke={hover.meta.color} strokeWidth={1} rx={3} />
              <text x={tx + 8} y={ty + 13} fontSize={9} fontWeight={700} fill={hover.meta.color}>
                {hover.meta.label} {hover.ballot ? `· ${hover.ballot}` : ''}
              </text>
              <text x={tx + 8} y={ty + 25} fontSize={8} fill={C.t2}>
                {hover.version} · {hover.date}
              </text>
              {hover.total !== null ? (
                <text x={tx + 8} y={ty + 37} fontSize={8} fill={C.tx}>
                  {hover.total.toLocaleString()} obligations
                  {hover.delta !== undefined && hover.delta !== 0 &&
                    ` (${hover.delta > 0 ? '+' : ''}${hover.delta})`}
                </text>
              ) : (
                <text x={tx + 8} y={ty + 37} fontSize={8} fill={C.t3}>
                  {isRug ? 'Count not computed for this ballot' : 'No obligation data'}
                </text>
              )}
              {hover.desc && (
                <text x={tx + 8} y={ty + (hover.total !== null ? 51 : 51)} fontSize={7.5} fill={C.t3}>
                  {hover.desc.length > 32 ? hover.desc.slice(0, 32) + '…' : hover.desc}
                </text>
              )}
            </g>
          );
        })()}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px',
        marginTop: 6, paddingTop: 8, borderTop: `1px solid ${C.bd}` }}>
        {Object.entries(DOC_META).map(([doc, meta]) => {
          const timeline = docTimelines[doc]?.timeline || [];
          const computed = timeline.filter(e => e.computed).length;
          const total = timeline.length;
          if (total === 0) return null;
          return (
            <div key={doc} onClick={() => setFocusDoc(focusDoc === doc ? null : doc)}
              style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer',
                opacity: isActive(doc) ? 1 : 0.3, fontSize: 9 }}>
              <svg width={24} height={10}>
                <line x1={0} y1={5} x2={24} y2={5} stroke={meta.color} strokeWidth={2} />
                <circle cx={12} cy={5} r={3} fill={meta.color} />
              </svg>
              <span style={{ color: C.tx, fontWeight: 600 }}>{meta.label}</span>
              <span style={{ color: C.t3 }}>{computed}/{total} counted</span>
            </div>
          );
        })}
        <span style={{ marginLeft: 'auto', fontSize: 8, color: C.t3, alignSelf: 'center' }}>
          Line = obligation count · Ticks below axis = ballot date only
        </span>
      </div>

      <div style={{ fontSize: 8, color: C.t3, marginTop: 6, lineHeight: 1.6 }}>
        Obligation counts from git-tagged versions; ballot dates from document revision tables.
        Where git tags are missing (TLS BR 2022–2024, S/MIME BR pre-adoption), only the ballot
        date tick is shown. Dot size ∝ obligation delta at that version. Click legend to isolate.
      </div>
    </Card>
  );
}
