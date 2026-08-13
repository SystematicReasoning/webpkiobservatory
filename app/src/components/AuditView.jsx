import React, { useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  Cell, ScatterChart, Scatter, ZAxis, ReferenceLine,
  CartesianGrid, ResponsiveContainer, LabelList,
} from 'recharts';
import { COLORS, ALPHA, FONT_MONO, FONT_SANS, STORE_COLORS } from '../constants';
import {
  Card, CardTitle, StatCard, ChartWrap,
  TabIntro, MethodologyCard, MethodologyItem,
  useIsMobile,
} from './shared';
import { usePipeline } from '../PipelineContext';
import {
  cardHeaderStyle, compactTableStyle, controlRowStyle,
  narrowStatGrid, scrollXStyle,
} from '../styles';

const C = COLORS;

// ── Compute per-auditor detection rates from retrospective data ───────────────
// Uses audit_timeline.auditor joined to bug_retrospective via stmt_date,
// giving per-letter auditor attribution rather than just primary_auditor.
// ── Shared inline Recent/All toggle for individual charts ─────────────────────
function InlineToggle({ value, onChange }) {
  // value=true means "Recent only", false means "All"
  const btn = active => ({
    padding: '2px 8px', fontSize: 10, borderRadius: 3, cursor: 'pointer',
    border: `1px solid ${active ? C.ac : C.bd}`,
    background: active ? ALPHA.ac09 : 'transparent',
    color: active ? C.ac : C.t3, fontWeight: active ? 600 : 400,
  });
  return (
    <div style={{ display: 'flex', gap: 2, flexShrink: 0, alignSelf: 'flex-start', marginTop: 2 }}>
      <button style={btn(value)}  onClick={() => onChange(true)}>Recent</button>
      <button style={btn(!value)} onClick={() => onChange(false)}>All</button>
    </div>
  );
}

function computeAuditorDetection(profiles, recentOnly = false) {
  const cutoffYear = new Date().getFullYear() - 2; // periods ending 2023+
  const stats = {};
  for (const p of profiles) {
    const stmtToAud = {};
    const stmtToPeriodEnd = {};
    for (const e of (p.audit_timeline ?? [])) {
      if (e.stmt_date && e.auditor) {
        stmtToAud[e.stmt_date] = e.auditor;
        stmtToPeriodEnd[e.stmt_date] = e.period_end;
      }
    }
    for (const r of (p.bug_retrospective ?? [])) {
      const isMulti = (r.missed_by ?? 0) >= 2;
      for (const c of (r.audit_coverage ?? [])) {
        const aud = stmtToAud[c.stmt_date] ?? p.primary_auditor;
        if (!aud) continue;
        // When recentOnly: skip audit periods that ended before the cutoff year
        if (recentOnly) {
          const periodEnd = stmtToPeriodEnd[c.stmt_date] ?? c.period_end ?? '';
          if (periodEnd && periodEnd.slice(0, 4) < String(cutoffYear)) continue;
        }
        if (!stats[aud]) stats[aud] = { caught: 0, missed: 0, multiCycle: 0, cas: new Set() };
        if (c.mentioned) stats[aud].caught++;
        else {
          stats[aud].missed++;
          if (isMulti) stats[aud].multiCycle++;
        }
        stats[aud].cas.add(p.ca_owner);
      }
    }
  }
  return Object.entries(stats)
    .map(([name, s]) => ({
      name,
      caught: s.caught, missed: s.missed,
      total: s.caught + s.missed,
      rate: s.caught + s.missed > 0 ? Math.round(s.caught / (s.caught + s.missed) * 100) : null,
      multiCycle: s.multiCycle,
      caCount: s.cas.size,
    }))
    .filter(r => r.total >= 3)  // need enough data to be meaningful
    .sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1));
}

// ── palette ──────────────────────────────────────────────────────────────────
const EPOCH_COLORS = { pre_aal: C.g5, aal_v3x: C.cy, post_v35: C.gn };
const epochShort   = { pre_aal: 'pre-2020', aal_v3x: '2020–2026', post_v35: '2026+' };
const epochLabel   = { pre_aal: 'Pre-2020 standards', aal_v3x: '2020–2026 standards', post_v35: '2026+ standards' };

// ── helpers ───────────────────────────────────────────────────────────────────
const fmt1    = v => v == null ? '—' : Number(v).toFixed(1);
const fmtPct  = v => v == null ? '—' : `${Math.round(v)}%`;
const gapColor = lvl => lvl === 'high' ? C.rd : lvl === 'moderate' ? C.am : lvl === 'low' ? C.gn : C.t3;

function qualityGrade(score) {
  if (score == null) return null;
  if (score >= 90) return { grade: 'A', color: C.gn };
  if (score >= 75) return { grade: 'B', color: C.gn };
  if (score >= 60) return { grade: 'C', color: C.am };
  if (score >= 40) return { grade: 'D', color: C.am };
  return { grade: 'F', color: C.rd };
}

// ── small atoms ───────────────────────────────────────────────────────────────
function GapBadge({ level }) {
  const cfg = {
    high:     { color: C.gn, label: 'High transparency',     dot: '●' },
    moderate: { color: C.am, label: 'Partial transparency',  dot: '●' },
    low:      { color: C.rd, label: 'Low transparency',      dot: '●' },
    unknown:  { color: C.t3, label: '—',                     dot: '○' },
  }[level] ?? { color: C.t3, label: '—', dot: '○' };
  const tip = {
    high:    "In-period disclosure rate ≥ 70%: the current audit letter mentions most incidents that were open during the audit period.",
    low:     "In-period disclosure rate < 30%: most incidents open during the audit period were not mentioned in the current letter. See bug retrospective below.",
    moderate:"In-period disclosure rate 30–69%: the current audit letter mentions some incidents that were open during the audit period.",
    unknown: "No in-period incident data available for this CA.",
  }[level] ?? '';
  return (
    <span style={{ fontSize: 11, color: cfg.color, whiteSpace: 'nowrap' }} title={tip}>
      {cfg.dot} {cfg.label}
    </span>
  );
}

/**
 * Compute the transparency level for a profile.
 * Prefers incident_disclosure_check.disclosure_rate (in-period, exact) when available.
 * Falls back to transparency_gap.gap_level (all-time coverage proxy) when not.
 * Returns: 'high' | 'moderate' | 'low' | 'unknown'
 */
function effectiveTransparencyLevel(p) {
  const dr = p?.incident_disclosure_check?.disclosure_rate;
  if (dr != null) {
    // disclosure_rate: 0–100, higher = better
    if (dr >= 70) return 'high';
    if (dr >= 30) return 'moderate';
    return 'low';
  }
  // Fallback: gap_level is inverted (high gap = low transparency)
  const gl = p?.transparency_gap?.gap_level;
  if (gl === 'high')     return 'low';
  if (gl === 'moderate') return 'moderate';
  if (gl === 'low')      return 'high';
  return 'unknown';
}

function EpochBadge({ epoch }) {
  const color = EPOCH_COLORS[epoch] ?? C.t3;
  return (
    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3,
      border: `1px solid ${color}`, color, whiteSpace: 'nowrap' }}>
      {epochShort[epoch] ?? epoch ?? '—'}
    </span>
  );
}

function ScoreBar({ value }) {
  if (value == null) return <span style={{ color: C.t3, fontSize: 11 }}>—</span>;
  const g = qualityGrade(value);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} title={`Audit report quality score: ${Math.round(value)}/100 — grades the quality of the audit report as a document, not the CA's compliance record`}>
      <span style={{ fontSize: 12, fontWeight: 700, color: g.color, minWidth: 14 }}>{g.grade}</span>
      <div style={{ flex: 1, height: 4, background: C.s2, borderRadius: 2, minWidth: 32 }}>
        <div style={{ width: `${value}%`, height: '100%', background: g.color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

function PdfPendingInline() {
  return (
    <div style={{ padding: '10px 14px', borderRadius: 6, fontSize: 12,
      background: C.s2, border: `1px solid ${C.bd}`, color: C.t2,
      display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ color: C.am, fontWeight: 500 }}>⏳</span>
      Requires the daily pipeline run with API access. Populates after next CI run.
    </div>
  );
}

function SectionHead({ children }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 500, color: C.t3, textTransform: 'uppercase',
      letterSpacing: '0.06em', margin: '32px 0 12px', borderBottom: `1px solid ${C.bd}`,
      paddingBottom: 8 }}>
      {children}
    </div>
  );
}

// ── CHART: Auditor changes ───────────────────────────────────────────────────
function AuditorChangesChart({ profiles, insight }) {
  const data = useMemo(() => {
    const byYear = {};
    profiles.forEach(p => {
      (p.timeline_trends?.auditor_changes ?? []).forEach(c => {
        const yr = String(c.year);
        if (!byYear[yr]) byYear[yr] = { year: yr, changes: 0, examples: [] };
        byYear[yr].changes++;
        byYear[yr].examples.push(`${p.ca_owner}: ${c.from_auditor} → ${c.to_auditor}`);
      });
    });
    return Object.values(byYear).sort((a, b) => a.year.localeCompare(b.year));
  }, [profiles]);

  const peakYear = useMemo(() => {
    if (!data.length) return null;
    return data.reduce((a, b) => b.changes > a.changes ? b : a).year;
  }, [data]);

  return (
    <Card>
      <CardTitle sub="Each bar is one year. Hover to see which CAs switched and to which firm.">
        How often CAs switch auditors
      </CardTitle>
      <div style={{ overflowX: 'auto' }}>
      <ChartWrap height={200} style={{ minWidth: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" stroke={C.bd} strokeOpacity={0.4} />
          <XAxis dataKey="year" tick={{ fontSize: 10, fill: C.t3 }} />
          <YAxis tick={{ fontSize: 10, fill: C.t3 }} allowDecimals={false} width={28} />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload;
            return (
              <div style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 6,
                padding: '8px 12px', fontSize: 12, maxWidth: 280 }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>
                  {d.year} — {d.changes} change{d.changes !== 1 ? 's' : ''}
                </div>
                {d.examples.slice(0, 5).map((ex, i) => (
                  <div key={`${i}-${ex.slice(0,20)}`} style={{ color: C.t2, fontSize: 11 }}>{ex}</div>
                ))}
                {d.examples.length > 5 && (
                  <div style={{ color: C.t3, fontSize: 11 }}>+{d.examples.length - 5} more</div>
                )}
              </div>
            );
          }} />
          <Bar dataKey="changes" radius={[3, 3, 0, 0]} maxBarSize={36}>
            {data.map(d => (
              <Cell key={d.year} fill={d.year === peakYear ? C.rd : C.am} />
            ))}
          </Bar>
        </BarChart>
        </ResponsiveContainer>
      </ChartWrap>
      </div>
      {insight && (
        <p style={{ fontSize: 11, color: C.t2, margin: '8px 0 0', fontStyle: 'italic' }}>{insight}</p>
      )}
    </Card>
  );
}

// ── CHART: Self-report by framework ─────────────────────────────────────────
function SelfReportChart({ profiles, insight }) {
  const data = useMemo(() =>
    ['WebTrust', 'ETSI'].map(fw => {
      const g = profiles.filter(p => p.primary_framework === fw && p.self_report_pct != null);
      const avg = g.length ? Math.round(g.reduce((s, p) => s + p.self_report_pct, 0) / g.length) : null;
      return { framework: fw, selfReport: avg, external: avg != null ? 100 - avg : null, n: g.length };
    }), [profiles]);

  return (
    <Card>
      <CardTitle sub="Share of Bugzilla compliance incidents where the CA itself filed the report first, by audit framework — not the auditor. This measures CA self-disclosure behavior: whether the CA's own monitoring found the issue before external parties did. Auditor detection (whether the formal audit letter mentions the incident) is measured separately in the section below.">
        Do CAs find their own problems?
      </CardTitle>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8, fontSize: 11, color: C.t2 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: C.gn, display: 'inline-block' }} />
          Self-reported
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: C.g5, display: 'inline-block' }} />
          Externally found
        </span>
      </div>
      <div style={{ overflowX: 'auto' }}>
      <ChartWrap height={140} style={{ minWidth: 280 }}>
        <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 48, bottom: 4, left: 64 }}>
          <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`}
            tick={{ fontSize: 10, fill: C.t3 }} />
          <YAxis type="category" dataKey="framework" tick={{ fontSize: 12, fill: C.t2 }} width={60} />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0]?.payload;
            return (
              <div style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 6,
                padding: '8px 12px', fontSize: 12 }}>
                <div style={{ fontWeight: 500 }}>{d.framework}</div>
                <div style={{ color: C.t2 }}>Self-reported: <b style={{ color: C.gn }}>{d.selfReport}%</b></div>
                <div style={{ color: C.t2 }}>Externally found: <b style={{ color: C.tx }}>{d.external}%</b></div>
                <div style={{ color: C.t2 }}>n = {d.n} CAs with incident data</div>
              </div>
            );
          }} />
          <Bar dataKey="selfReport" stackId="a" fill={C.gn} maxBarSize={28} />
          <Bar dataKey="external"   stackId="a" fill={C.g5} radius={[0, 3, 3, 0]} maxBarSize={28} />
        </BarChart>
        </ResponsiveContainer>
      </ChartWrap>
      </div>
      {insight && (
        <p style={{ fontSize: 11, color: C.t2, margin: '8px 0 0', fontStyle: 'italic' }}>{insight}</p>
      )}
    </Card>
  );
}

// ── CALLOUT: Key ecosystem insight ──────────────────────────────────────────
function EcosystemInsight({ profiles }) {
  const veryStale    = profiles.filter(p => p.staleness === 'very_stale');
  const msExclusive  = veryStale.filter(p => p.exclusive_store === 'microsoft');
  const multiStore   = profiles.filter(p => !p.exclusive_store && p.trusted_stores?.length > 1);
  const multiStale   = multiStore.filter(p => p.staleness === 'very_stale');

  const scored       = profiles.filter(p => p.transparency_gap?.gap_score != null || p.incident_disclosure_check?.disclosure_rate != null);
  const highGap      = scored.filter(p => effectiveTransparencyLevel(p) === 'low');

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 500, color: C.tx, marginBottom: 6 }}>
          Stale audits concentrate in Microsoft's store
        </div>
        <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.7 }}>
          {veryStale.length > 0
            ? <>{msExclusive.length} of {veryStale.length} very-stale CAs appear only in Microsoft's
                trust store — not Chrome, Firefox, or Apple.
                {multiStale.length === 0 && ' No CA trusted by multiple browsers has a very stale audit.'}
                {' '}CAs in multiple stores face more scrutiny and tend to maintain current audit coverage.</>
            : <>No very-stale CAs in the current view. All CAs have audit letters issued within the past two years.</>
          }
        </div>
      </Card>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 500, color: C.tx, marginBottom: 6 }}>
          A clean audit letter is not the same as a clean incident record
        </div>
        <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.7 }}>
          {scored.length > 0
            ? <>{highGap.length} of {scored.length} CAs with audit data show low in-period transparency —
                fewer than 30% of incidents open during their current audit period were mentioned in the letter.
                Where in-period data is unavailable, the all-time Bugzilla citation rate is used as a proxy.</>
            : <>Transparency data not yet available for this view.</>
          }
        </div>
      </Card>
    </div>
  );
}

// ── CARD: WebTrust vs ETSI framework comparison ──────────────────────────────
function FrameworkComparisonCard({ profiles }) {
  const data = useMemo(() => {
    return ['WebTrust', 'ETSI'].map(fw => {
      const group  = profiles.filter(p => p.primary_framework === fw);
      const parsed = group.filter(p => p.pdf_parsed);
      const scored = parsed.filter(p => p.letter_quality_score?.overall != null);
      const avgQ   = scored.length
        ? Math.round(scored.reduce((s, p) => s + p.letter_quality_score.overall, 0) / scored.length)
        : null;
      let caught = 0, covered = 0;
      for (const p of group) {
        for (const r of (p.bug_retrospective ?? [])) {
          if (r.covering_letters > 0) {
            covered++;
            if (r.mentioned_in > 0) caught++;
          }
        }
      }
      const det = covered > 0 ? Math.round(caught / covered * 100) : null;
      const stale = group.filter(p => ['stale','very_stale'].includes(p.staleness)).length;
      return { fw, n: group.length, parsed: parsed.length, avgQ, caught, covered, det, stale };
    });
  }, [profiles]);

  // Within-CA comparison — CAs with both frameworks parsed
  const dual = useMemo(() => {
    return profiles
      .filter(p => p.secondary_audit && p.pdf_parsed)
      .map(p => {
        const s = p.secondary_audit;
        const lqs = v => { if (!v) return null; if (typeof v === 'object') return v.overall; return +v; };
        return {
          ca:        p.ca_owner,
          caType:    p.ca_type,
          primary:   {
            fw:          p.audit_framework ?? '?',
            auditor:     p.primary_auditor,
            opinion:     p.opinion_type,
            quality:     lqs(p.letter_quality_score),
            fpInLetter:  (p.in_scope_sha256 ?? []).length,
            subCaFps:    (p.fingerprint_check?.engagement_fps_extra_intermediates ?? []).length,
            notInCcadb:  (p.fingerprint_check?.engagement_fps_extra_undisclosed ?? []).length,
            scopeGaps:   p.oid_check?.gaps ?? [],
            url:         p.tls_br_pdf_url,
          },
          secondary: {
            fw:          s.fw_label ?? s.framework ?? '?',
            auditor:     s.auditor,
            opinion:     s.opinion_type,
            quality:     lqs(s.quality_score),
            fpInLetter:  (s.in_scope_sha256 ?? []).length,
            subCaFps:    (s.fingerprint_check?.engagement_fps_extra_intermediates ?? []).length,
            notInCcadb:  (s.fingerprint_check?.engagement_fps_extra_undisclosed ?? []).length,
            scopeGaps:   s.oid_check?.gaps ?? [],
            url:         s.url,
          },
        };
      })
      .sort((a, b) => a.ca.localeCompare(b.ca));
  }, [profiles]);

  const cols = ['WebTrust', 'ETSI'];
  const [wt, et] = data;

  const Row = ({ label, wt: wv, et: ev, sub }) => (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(80px, 1fr))', gap: 8, padding: '6px 0',
      borderBottom: `1px solid ${C.bd}`, alignItems: 'center' }}>
      <div style={{ fontSize: 11, color: C.t2 }}>{label}
        {sub && <div style={{ fontSize: 10, color: C.t3 }}>{sub}</div>}
      </div>
      {[wv, ev].map((v, i) => (
        <div key={i} style={{ fontSize: 13, fontWeight: 600, color: C.tx, textAlign: 'right' }}>{v ?? '—'}</div>
      ))}
    </div>
  );

  function FwBadge({ fw }) {
    const isEtsi = fw === 'ETSI';
    return (
      <span style={{ display: 'inline-block', padding: '1px 6px', borderRadius: 3,
        fontSize: 10, fontWeight: 600, letterSpacing: '0.03em',
        background: isEtsi ? ALPHA.ac13 : ALPHA.gn13,
        color: isEtsi ? C.ac : C.gn,
        border: `1px solid ${isEtsi ? ALPHA.ac27 : ALPHA.gn27}` }}>
        {fw}
      </span>
    );
  }

  function OpinionDot({ opinion }) {
    const color = opinion === 'unqualified' ? C.gn : opinion === 'qualified' ? C.am : C.t3;
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0 }} />
        <span style={{ fontSize: 11, color: opinion === 'unqualified' ? C.t2 : color }}>{opinion ?? '—'}</span>
      </span>
    );
  }

  const thS = { padding: '5px 8px', fontSize: 10, fontWeight: 600, color: C.t3,
    textTransform: 'uppercase', letterSpacing: '0.05em', textAlign: 'left',
    borderBottom: `1px solid ${C.bd}`, whiteSpace: 'normal', verticalAlign: 'bottom' };
  const thR = { ...thS, textAlign: 'right' };

  return (
    <Card>
      <CardTitle sub="WebTrust is a CPA Canada/AICPA standard applied by North American and global accounting firms. ETSI is the European standard; letters must follow the AAL (Audit Attestation Letter) template. Both frameworks cover the same CA/B Forum requirements.">
        WebTrust vs. ETSI — framework comparison
      </CardTitle>

      {/* ── Aggregate cross-sectional comparison ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(80px, 1fr))', gap: 8,
        padding: '4px 0 8px', borderBottom: `1px solid ${C.bd}`, marginBottom: 4 }}>
        <div />
        {cols.map(fw => (
          <div key={fw} style={{ fontSize: 12, fontWeight: 700, color: C.tx, textAlign: 'right' }}>{fw}</div>
        ))}
      </div>
      <Row label="CA owners"        wt={`${wt.n}`}   et={`${et.n}`} />
      <Row label="Letters parsed"   wt={`${wt.parsed}`} et={`${et.parsed}`} />
      <Row label="Avg letter quality" sub="0–100 score"
        wt={wt.avgQ != null ? `${wt.avgQ}/100` : null}
        et={et.avgQ != null ? `${et.avgQ}/100` : null} />
      <Row label="In-period detection" sub="incidents caught / covered"
        wt={wt.det != null ? `${wt.det}% (${wt.caught}/${wt.covered})` : null}
        et={et.det != null ? `${et.det}% (${et.caught}/${et.covered})` : null} />
      <Row label="Stale or very stale" sub="letter >1 year old"
        wt={`${wt.stale} of ${wt.n}`} et={`${et.stale} of ${et.n}`} />

      {/* ── Within-CA controlled experiment ── */}
      {dual.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: C.t2, marginBottom: 4 }}>
            Within-CA comparison — {dual.length} CA{dual.length !== 1 ? 's' : ''} with both frameworks
          </div>
          <div style={{ fontSize: 11, color: C.t3, marginBottom: 10, lineHeight: 1.5 }}>
            Same CA, same audit period, two frameworks. Any difference between rows for the same CA
            reflects the auditor and framework — not the CA's underlying compliance posture.
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ ...compactTableStyle, width: '100%' }}>
              <thead>
                <tr>
                  <th style={{ ...thS, position: 'sticky', left: 0, background: 'var(--bg,#111)', zIndex: 2 }}>CA</th>
                  <th style={thS}>Framework</th>
                  <th style={thS}>Auditor</th>
                  <th style={thS}>Opinion</th>
                  <th style={thR}>Quality</th>
                  <th style={thR}>Sub-CAs<br/>in letter</th>
                  <th style={thR}>Attested,<br/>not in CCADB</th>
                  <th style={thS}>Scope gaps</th>
                  <th style={thS}>Letter</th>
                </tr>
              </thead>
              <tbody>
                {dual.map(({ ca, caType, primary, secondary }) => {
                  const tdB = { padding: '5px 8px', fontSize: 12, color: C.tx, verticalAlign: 'middle' };
                  const tdR = { ...tdB, textAlign: 'right' };
                  const top = { borderTop: `2px solid ${C.bd}` };
                  return [primary, secondary].map((letter, idx) => (
                    <tr key={`${ca}-${idx}`} style={{ background: idx === 1 ? ALPHA.s250 : 'transparent' }}>
                      {idx === 0 && (
                        <td rowSpan={2} style={{ ...tdB, ...top, position: 'sticky', left: 0,
                            background: 'var(--bg,#111)', zIndex: 1, fontWeight: 600, maxWidth: 180 }}>
                          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                               title={ca}>{ca}</div>
                          {caType && (
                            <div style={{ fontSize: 9, color: C.t3, textTransform: 'uppercase',
                              letterSpacing: '0.04em', marginTop: 2 }}>{caType.replace('_',' ')}</div>
                          )}
                        </td>
                      )}
                      <td style={{ ...tdB, ...(idx === 0 ? top : {}) }}><FwBadge fw={letter.fw} /></td>
                      <td style={{ ...tdB, ...(idx === 0 ? top : {}), maxWidth: 140 }}>
                        <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                              title={letter.auditor}>{letter.auditor || '—'}</span>
                      </td>
                      <td style={{ ...tdB, ...(idx === 0 ? top : {}) }}>
                        <OpinionDot opinion={letter.opinion} />
                      </td>
                      <td style={{ ...tdR, ...(idx === 0 ? top : {}) }}>
                        {letter.quality != null
                          ? <span style={{ fontWeight: 600, color: letter.quality >= 75 ? C.gn : letter.quality >= 50 ? C.am : C.rd }}>
                              {letter.quality.toFixed(0)}
                            </span>
                          : <span style={{ color: C.t3 }}>—</span>}
                      </td>
                      <td style={{ ...tdR, ...(idx === 0 ? top : {}) }}>
                        <span style={{ color: letter.subCaFps > 0 ? C.t2 : C.t3 }}>
                          {letter.subCaFps || '—'}
                        </span>
                      </td>
                      <td style={{ ...tdR, ...(idx === 0 ? top : {}) }}>
                        <span style={{ color: letter.notInCcadb > 0 ? C.am : C.t3 }}>
                          {letter.notInCcadb || '—'}
                        </span>
                      </td>
                      <td style={{ ...tdB, ...(idx === 0 ? top : {}) }}>
                        {letter.scopeGaps?.length > 0
                          ? <span style={{ color: C.am, fontSize: 11 }}>{letter.scopeGaps.join(', ')}</span>
                          : <span style={{ color: C.gn, fontSize: 11 }}>none</span>}
                      </td>
                      <td style={{ ...tdB, ...(idx === 0 ? top : {}) }}>
                        {letter.url
                          ? <a href={letter.url} target="_blank" rel="noreferrer"
                               style={{ fontSize: 10, color: C.ac, textDecoration: 'none' }}>PDF ↗</a>
                          : <span style={{ color: C.t3, fontSize: 11 }}>—</span>}
                      </td>
                    </tr>
                  ));
                })}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 10, color: C.t3, marginTop: 6, lineHeight: 1.5 }}>
            ETSI eIDAS sub-CA letters may cover a different certificate hierarchy than the CCADB
            global root inventory for the same CA owner — European and global hierarchies can diverge.
            Quality scores and OID checks for secondary letters are LLM-parsed; fingerprints are
            regex-extracted where LLM parse is unavailable.
          </div>
        </div>
      )}
    </Card>
  );
}

// ── CHART: Transparency matrix ───────────────────────────────────────────────
function TransparencyMatrix({ profiles }) {
  const data = useMemo(() =>
    profiles
      .filter(p => p.letter_quality_score?.overall != null)
      .map(p => {
        // Use in-period disclosure_rate where available, fall back to all-time gap_score
        const dr = p.incident_disclosure_check?.disclosure_rate;
        const gap = dr != null
          ? (100 - dr)   // invert: 0% disclosure → 100 gap, 100% → 0 gap
          : p.transparency_gap?.gap_score;
        if (gap == null) return null;
        return {
          ca: p.ca_owner, quality: p.letter_quality_score.overall,
          gap, incidents: p.incident_count,
          framework: p.primary_framework, auditor: p.primary_auditor,
          gapSource: dr != null ? 'in-period' : 'all-time',
          r: Math.max(4, Math.min(16, 4 + Math.sqrt(p.root_count ?? 1) * 1.8)),
        };
      }).filter(Boolean), [profiles]);

  if (!data.length) return <PdfPendingInline />;

  const quadrantFill = d => {
    if (d.quality >= 70 && d.gap < 30)  return C.gn;
    if (d.quality >= 70 && d.gap >= 70) return C.am;
    if (d.quality < 70  && d.gap >= 70) return C.rd;
    return C.g5;
  };

  return (
    <Card>
      <CardTitle sub="Each bubble is one CA. X-axis: in-period disclosure gap (right = fewer in-scope incidents mentioned; uses in-period detection rate where available, all-time Bugzilla citation gap as fallback). Y-axis: letter quality score. Bubble size reflects number of root certificates.">
        Audit Letter Quality vs. Disclosure Gap
      </CardTitle>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 8, fontSize: 11, color: C.t2 }}>
        {[{ col: C.gn, l: 'High quality + high disclosure' },
          { col: C.am, l: 'High quality + low disclosure' },
          { col: C.rd, l: 'Low quality + low disclosure' },
          { col: C.g5, l: 'Low quality + high disclosure' }].map(({ col, l }) => (
          <span key={l} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: col, display: 'inline-block' }} />
            {l}
          </span>
        ))}
      </div>
      <div style={{ overflowX: 'auto' }}>
      <ChartWrap height={320} style={{ minWidth: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 16, right: 16, bottom: 32, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={C.bd} strokeOpacity={0.4} />
          <XAxis type="number" dataKey="gap" domain={[0, 105]}
            label={{ value: 'Disclosure gap → (right = more omitted)', position: 'insideBottom', offset: -16, fill: C.t3, fontSize: 11 }}
            tick={{ fontSize: 10, fill: C.t3 }} />
          <YAxis type="number" dataKey="quality" domain={[25, 115]}
            label={{ value: '← Letter quality', angle: -90, position: 'insideLeft', offset: 16, fill: C.t3, fontSize: 11 }}
            tick={{ fontSize: 10, fill: C.t3 }} width={40} />
          <ZAxis type="number" dataKey="r" range={[16, 256]} />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload;
            return (
              <div style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 6,
                padding: '8px 12px', fontSize: 12 }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>{d.ca}</div>
                <div style={{ color: C.t2 }}>Letter quality: <b style={{ color: C.tx }}>{fmt1(d.quality)}</b></div>
                <div style={{ color: C.t2 }}>Disclosure gap: <b style={{ color: C.tx }}>{fmtPct(d.gap)}</b>
                  <span style={{ fontSize: 10, color: C.t3, marginLeft: 4 }}>({d.gapSource})</span></div>
                <div style={{ color: C.t2 }}>Incidents: <b style={{ color: C.tx }}>{d.incidents ?? '—'}</b></div>
                <div style={{ color: C.t2 }}>Framework: <b style={{ color: C.tx }}>{d.framework}</b></div>
              </div>
            );
          }} />
          <ReferenceLine y={70} stroke={C.bd} strokeDasharray="4 4" />
          <Scatter data={data}
            shape={props => {
              const d = props.payload;
              const fill = quadrantFill(d);
              return <circle cx={props.cx} cy={props.cy} r={d.r}
                fill={fill} fillOpacity={0.65} stroke={fill} strokeWidth={0.5} />;
            }} />
        </ScatterChart>
        </ResponsiveContainer>
      </ChartWrap>
      </div>
    </Card>
  );
}

// ── CHART: Auditor scorecard ─────────────────────────────────────────────────
function AuditorScorecard({ aggregates }) {
  const [sortBy, setSortBy] = useState('quality');  // default: sort by quality

  const rows = useMemo(() => {
    const base = Object.entries(aggregates)
      .filter(([, a]) => a.ca_count >= 2 && a.avg_quality_score != null)
      .map(([name, a]) => ({
        name: name.length > 26 ? name.slice(0, 25) + '…' : name,
        fullName: name,
        score:  a.avg_quality_score,
        count:  a.ca_count,
        country: a.auditor_country,
        matters: a.avg_matters_per_ca,
      }));
    if (sortBy === 'count') base.sort((a, b) => b.count - a.count);
    else base.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    return base.slice(0, 14);
  }, [aggregates, sortBy]);

  const SortBtn = ({ id, label }) => (
    <button onClick={() => setSortBy(id)} style={{
      padding: '2px 8px', fontSize: 10, borderRadius: 3, cursor: 'pointer',
      border: `1px solid ${sortBy === id ? C.ac : C.bd}`,
      background: sortBy === id ? ALPHA.ac13 : 'transparent',
      color: sortBy === id ? C.ac : C.t3,
    }}>{label}</button>
  );

  if (!rows.length) return <PdfPendingInline />;

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <CardTitle sub="Average letter quality score (0–100) across each firm's current clients. Higher is better. For incident detection rates, see the chart above.">
          Audit firm letter quality comparison
        </CardTitle>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
          <span style={{ fontSize: 10, color: C.t3, marginRight: 2 }}>Sort:</span>
          <SortBtn id="quality" label="Quality" />
          <SortBtn id="count"   label="# Clients" />
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
      <ChartWrap height={Math.max(280, rows.length * 32 + 40)} style={{ minWidth: 340 }}>
        <ResponsiveContainer width="100%" height="100%">
        <BarChart layout="vertical" data={rows}
          margin={{ top: 4, right: 48, bottom: 4, left: 140 }}>
          <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke={C.bd} strokeOpacity={0.4} />
          <XAxis type="number" domain={[0, 100]} tickFormatter={v => v}
            tick={{ fontSize: 10, fill: C.t3 }} />
          <YAxis type="category" dataKey="name" width={150}
            tick={{ fontSize: 11, fill: C.t2 }} />
          <ReferenceLine x={75} stroke={C.bd} strokeDasharray="4 2"
            label={{ value: 'B', position: 'top', fill: C.t3, fontSize: 9 }} />
          <ReferenceLine x={60} stroke={C.bd} strokeDasharray="2 4"
            label={{ value: 'C', position: 'top', fill: C.t3, fontSize: 9 }} />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload;
            const g = qualityGrade(d.score);
            return (
              <div style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 6,
                padding: '8px 12px', fontSize: 12 }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>{d.fullName}</div>
                <div style={{ color: C.t2 }}>
                  Avg quality: <b style={{ color: g?.color ?? C.tx }}>
                    {g?.grade} ({fmt1(d.score)})
                  </b>
                </div>
                <div style={{ color: C.t2 }}>CAs audited: <b style={{ color: C.tx }}>{d.count}</b></div>
                <div style={{ color: C.t2 }}>Avg matters/CA: <b style={{ color: C.tx }}>{fmt1(d.matters)}</b></div>
                {d.country && <div style={{ color: C.t2 }}>Country: <b style={{ color: C.tx }}>{d.country}</b></div>}
              </div>
            );
          }} />
          <Bar dataKey="score" radius={[0, 3, 3, 0]} maxBarSize={16}>
            {rows.map((r, i) => (
              <Cell key={i} fill={qualityGrade(r.score)?.color ?? C.t3} />
            ))}
          </Bar>
        </BarChart>
        </ResponsiveContainer>
      </ChartWrap>
      </div>
      <p style={{ fontSize: 11, color: C.t3, margin: '8px 0 0' }}>
        Firms with fewer than 2 current clients excluded. Hover for client count and avg matters per CA.
        Scores are computed across all parsed letters for each firm regardless of the Recent/All filter —
        use the detection rate chart above for a recency-filtered view.
      </p>
    </Card>
  );
}

// ── CHART: Quality over time ─────────────────────────────────────────────────
// ── CHART: Auditor detection rates ───────────────────────────────────────────
function AuditorDetectionChart({ profiles, insight }) {
  const [recentOnly, setRecentOnly] = useState(true);

  const activeProfiles = useMemo(() =>
    recentOnly
      ? profiles.filter(p => p.staleness === 'current' || p.staleness === 'aging')
      : profiles,
    [profiles, recentOnly]);

  const rows = useMemo(() => computeAuditorDetection(activeProfiles, recentOnly), [activeProfiles, recentOnly]);
  if (!rows.length) return null;

  const shorten = n => n.length > 24 ? n.slice(0, 23) + '…' : n;
  const displayRows = rows.map(r => ({ ...r, shortName: shorten(r.name) }));

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <CardTitle sub="Each bar is one audit firm. The percentage shown is how often their clients' in-scope incidents appeared in the letter — denominator counts bugs filed while the audit period was open. See Methodology for the CCADB §5 scope note on pre-existing open bugs. Hover for counts.">
          Did auditors catch what was happening on their watch?
        </CardTitle>
        <InlineToggle value={recentOnly} onChange={setRecentOnly} />
      </div>
      <div style={{ overflowX: 'auto' }}>
      <ChartWrap height={Math.max(200, displayRows.length * 28 + 40)} style={{ minWidth: 340 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart layout="vertical" data={displayRows}
            margin={{ top: 4, right: 60, bottom: 4, left: 170 }}>
            <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke={C.bd} strokeOpacity={0.4} />
            <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`}
              tick={{ fontSize: 10, fill: C.t3 }} />
            <YAxis type="category" dataKey="shortName" width={160}
              tick={{ fontSize: 11, fill: C.t2 }} />
            <Tooltip content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 6,
                  padding: '8px 12px', fontSize: 12 }}>
                  <div style={{ fontWeight: 500, marginBottom: 4 }}>{d.name}</div>
                  <div style={{ color: C.t2 }}>
                    Mentioned in letter: <b style={{ color: C.tx }}>{d.rate}%</b>
                    <span style={{ color: C.t3 }}> ({d.caught} of {d.total} in-scope)</span>
                  </div>
                  <div style={{ color: C.t2 }}>CAs audited: <b style={{ color: C.tx }}>{d.caCount}</b></div>
                  {d.multiCycle > 0 && (
                    <div style={{ color: C.rd }}>
                      Multi-cycle misses: <b>{d.multiCycle}</b>
                    </div>
                  )}
                </div>
              );
            }} />
            <Bar dataKey="rate" radius={[0, 3, 3, 0]} maxBarSize={18} minPointSize={3}>
              {displayRows.map((r, i) => (
                <Cell key={i} fill={
                  r.rate >= 70 ? C.gn : r.rate >= 40 ? C.am : C.rd
                } />
              ))}
              <LabelList dataKey="rate" position="right" fontSize={10} fill={C.t3}
                formatter={v => v === 0 ? '0%' : ''} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartWrap>
      </div>
      <div style={{ fontSize: 11, color: C.t3, marginTop: 8 }}>
        Only auditors with 3+ in-scope incidents shown. Hover each bar for caught/total counts.
      </div>
      {insight && (
        <p style={{ fontSize: 11, color: C.t2, margin: '8px 0 0', fontStyle: 'italic' }}>{insight}</p>
      )}
    </Card>
  );
}

// ── CHART: Audit letter completeness (ALV-equivalent) ────────────────────────
function AuditLetterCompleteness({ profiles, summary }) {
  const parsed = profiles.filter(p => p.pdf_parsed);
  const [viewMode, setViewMode] = useState('auditor'); // 'ca' | 'auditor'
  const [caFilter, setCaFilter] = useState('all'); // 'all' | 'fp' | 'scope' | 'pass'
  const [caSearch, setCaSearch] = useState('');
  const [sortCol, setSortCol]   = useState('missingFps');
  const [sortDir, setSortDir]   = useState('desc');
  const isMobile = useIsMobile();
  if (!parsed.length) return null;

  const rows = useMemo(() => {
    return parsed.map(p => {
      const fc  = p.fingerprint_check ?? {};
      const oc  = p.oid_check ?? {};
      const rc  = p.root_coverage ?? {};

      const missingFps     = fc.engagement_fps_missing?.length ?? 0;
      const extraFps       = fc.engagement_fps_extra?.length ?? 0;
      const subCaFps       = fc.engagement_fps_extra_intermediates?.length ?? 0;  // sub-CAs / issuing CAs in letter (CCADB Intermediate Certificate records)
      const unregisteredFps = fc.engagement_fps_extra_undisclosed?.length ?? 0;   // in letter, no CCADB record at all (cross-certs, eIDAS, undisclosed sub-CAs)
      const crossSignedMissing = fc.cross_signed_fps_missing?.length ?? 0;         // §5.1: cross-signed certs this CA issued, absent from letter
      const scopeGaps      = oc.gaps ?? [];
      const scopeGapNote   = p.scope_gap_note ?? null;
      const untracedRoots  = rc.roots_without_url ?? 0;

      // disclosedFps / undisclosedFps kept as aliases for backward-compat with sort keys
      const disclosedFps   = subCaFps;
      const undisclosedFps = unregisteredFps;

      const issues = [];
      if (missingFps > 0) issues.push(`${missingFps} trusted root${missingFps > 1 ? 's' : ''} absent from letter`);
      if (scopeGaps.length > 0) issues.push(`scope gaps: ${scopeGaps.slice(0, 2).join(', ')}${scopeGaps.length > 2 ? ` +${scopeGaps.length - 2}` : ''}`);
      if (crossSignedMissing > 0) issues.push(`${crossSignedMissing} cross-signed cert${crossSignedMissing > 1 ? 's' : ''} absent from letter (§5.1)`);

      // Sub-CA FPs, removed-root FPs, and unregistered FPs are informational.
      // Untraced = roots with no audit URL (ecosystem coverage gap, not letter deficiency).
      const warnings = [];
      if (untracedRoots > 0)    warnings.push(`${untracedRoots} root${untracedRoots > 1 ? 's' : ''} with no audit URL`);
      if (unregisteredFps > 0)  warnings.push(`${unregisteredFps} cert${unregisteredFps > 1 ? 's' : ''} in letter not in any CCADB record`);

      return {
        ca: p.ca_owner,
        auditor: p.primary_auditor ?? 'Unknown',
        trustedStores: p.trusted_stores ?? [],
        caType: p.ca_type ?? 'commercial',
        missingFps, extraFps, subCaFps, unregisteredFps, crossSignedMissing,
        disclosedFps, undisclosedFps,  // aliases
        scopeGaps, scopeGapNote, untracedRoots,
        issueCount: issues.length,
        issues,
        warnings,
        pass: issues.length === 0,
      };
    }).sort((a, b) => b.issueCount - a.issueCount);
  }, [parsed]);

  // Auditor-grouped view
  const auditorRows = useMemo(() => {
    const byAud = {};
    for (const r of rows) {
      const k = r.auditor;
      if (!byAud[k]) byAud[k] = {
        auditor: k, total: 0,
        scopeGap: 0, pass: 0,
        totalMissingRoots:    0,  // trusted roots absent from letter
        totalSubCaFps:        0,  // sub-CAs / issuing CAs in letter (CCADB Intermediate)
        totalUnregistered:    0,  // certs in letter absent from all CCADB records
        totalCrossSignedMiss: 0,  // §5.1 cross-signed certs absent from letter
      };
      byAud[k].total++;
      byAud[k].totalMissingRoots    += r.missingFps;
      byAud[k].totalSubCaFps        += r.subCaFps;
      byAud[k].totalUnregistered    += r.unregisteredFps;
      byAud[k].totalCrossSignedMiss += r.crossSignedMissing;
      if (r.scopeGaps.length > 0) byAud[k].scopeGap++;
      if (r.pass) byAud[k].pass++;
    }
    return Object.values(byAud)
      .filter(a => a.total >= 2)
      .sort((a, b) => b.scopeGap - a.scopeGap);
  }, [rows]);

  const passing    = rows.filter(r => r.pass).length;
  const withIssues = rows.filter(r => !r.pass).length;
  const fpMissing  = rows.filter(r => r.missingFps > 0).length;
  const scopeGap   = rows.filter(r => r.scopeGaps.length > 0).length;
  const untraced   = rows.filter(r => r.untracedRoots > 0).length;
  const crossSignedGap = rows.filter(r => r.crossSignedMissing > 0).length;

  const filteredRows = useMemo(() => {
    let r = rows;
    if (caFilter === 'fp')    r = r.filter(x => x.missingFps > 0);
    if (caFilter === 'scope') r = r.filter(x => x.scopeGaps.length > 0);
    if (caFilter === 'pass')  r = r.filter(x => x.pass);
    if (caFilter === 'all')   r = r.filter(x => !x.pass);
    if (caSearch.trim()) {
      const q = caSearch.trim().toLowerCase();
      r = r.filter(x => x.ca.toLowerCase().includes(q) || x.auditor.toLowerCase().includes(q));
    }
    // Sort
    r = [...r].sort((a, b) => {
      let av, bv;
      if (sortCol === 'ca')             { av = a.ca; bv = b.ca; }
      else if (sortCol === 'missingFps')     { av = a.missingFps;      bv = b.missingFps; }
      else if (sortCol === 'scopeGaps')      { av = a.scopeGaps.length; bv = b.scopeGaps.length; }
      else if (sortCol === 'subCaFps')       { av = a.subCaFps;        bv = b.subCaFps; }
      else if (sortCol === 'undisclosedFps') { av = a.unregisteredFps; bv = b.unregisteredFps; }
      else if (sortCol === 'extraFps')       { av = a.unregisteredFps; bv = b.unregisteredFps; } // legacy
      else if (sortCol === 'disclosedFps')   { av = a.subCaFps;        bv = b.subCaFps; }        // legacy
      else if (sortCol === 'untraced')       { av = a.untracedRoots;   bv = b.untracedRoots; }
      else if (sortCol === 'stores')         { av = a.trustedStores.length; bv = b.trustedStores.length; }
      else if (sortCol === 'caType')      { av = a.caType; bv = b.caType; }
      else { av = a.missingFps; bv = b.missingFps; }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return r;
  }, [rows, caFilter, caSearch, sortCol, sortDir]);

  const onSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('desc'); }
  };
  const sortArrow = col => sortCol === col ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '';

  const thS = { padding: '6px 10px', fontSize: 10, fontWeight: 600, color: C.t3,
    borderBottom: `1px solid ${C.bd}`, textAlign: 'left', textTransform: 'uppercase',
    letterSpacing: '0.04em', whiteSpace: 'nowrap' };
  const thR = { ...thS, textAlign: 'right' };

  const toggleBtn = active => ({
    padding: '2px 8px', fontSize: 10, borderRadius: 3, cursor: 'pointer',
    border: `1px solid ${active ? C.ac : C.bd}`,
    background: active ? ALPHA.ac09 : 'transparent',
    color: active ? C.ac : C.t3, fontWeight: active ? 600 : 400,
  });

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
        <CardTitle sub="Two checks per letter: (1) does it list SHA-256 fingerprints for the roots assigned to its audit URL in CCADB? (2) does it declare coverage for all certificate types the CA is trusted to issue, or are separate per-criteria letters on file? The first check is passing for all 82 parsed letters. The second check (scope coverage) identifies 9 CAs with genuine gaps. Note: TLS DV and TLS OV are both covered by the single TLS BR document — they appear as separate gaps only when a non-standard criteria profile (e.g. ETSI NCP+OVCP) covers one level but not the other. TLS EV, S/MIME, and Code Signing each require a separate dedicated letter.">
          {passing === rows.length
            ? 'All parsed audit letters pass fingerprint and scope checks'
            : passing === 0
              ? 'No parsed audit letters pass both fingerprint and scope checks'
              : `${rows.length - passing} of ${rows.length} audit letters fail fingerprint or scope checks`}
        </CardTitle>
        <div style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
          <button style={toggleBtn(viewMode === 'auditor')} onClick={() => setViewMode('auditor')}>By Auditor</button>
          <button style={toggleBtn(viewMode === 'ca')}      onClick={() => setViewMode('ca')}>By CA</button>
        </div>
      </div>

      {/* Summary chips */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {[
          { label: 'Pass all checks',              v: passing,          c: passing > 0 ? C.gn : C.t3 },
          { label: 'Roots not in letter',           v: fpMissing,        c: fpMissing > 0 ? C.rd : C.t3 },
          { label: 'Certificate scope gaps',        v: scopeGap,         c: scopeGap > 0 ? C.am : C.t3 },
          { label: 'No audit URL for some roots',   v: untraced,         c: untraced > 0 ? C.am : C.t3 },
          { label: 'Cross-signed certs missing (§5.1)', v: crossSignedGap, c: crossSignedGap > 0 ? C.am : C.t3 },
        ].map(({ label, v, c }) => (
          <div key={label} style={{ padding: '8px 12px', borderRadius: 6, background: C.s2,
            border: `1px solid ${C.bd}`, minWidth: 90, flex: '1 1 90px' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: c }}>{v}</div>
            <div style={{ fontSize: 10, color: C.t2, marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, color: C.t3, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Trusted by:</span>
        {[
          { key: 'mozilla',   label: 'Mozilla',    color: STORE_COLORS.mozilla },
          { key: 'chrome',    label: 'Chrome',     color: STORE_COLORS.chrome },
          { key: 'microsoft', label: 'Microsoft',  color: STORE_COLORS.microsoft },
          { key: 'apple',     label: 'Apple',      color: STORE_COLORS.apple },
        ].map(({ key, label, color }) => (
          <span key={key} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, color: C.t2 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {label}
          </span>
        ))}
        <span style={{ fontSize: 10, color: C.t3, marginLeft: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.bd, border: `1px solid ${C.bl}`, display: 'inline-block', verticalAlign: 'middle', marginRight: 4 }} />
          Not trusted
        </span>
      </div>

      {/* By CA view */}
      {viewMode === 'ca' && (
        <>
          {/* Filter bar */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            {[
              { key: 'all',   label: `All (${withIssues})` },
              { key: 'fp',    label: `Roots not in letter (${fpMissing})` },
              { key: 'scope', label: `Scope gaps (${scopeGap})` },
              { key: 'pass',  label: `Pass (${passing})` },
            ].map(({ key, label }) => (
              <button key={key} onClick={() => setCaFilter(key)} style={{
                padding: '2px 8px', fontSize: 10, borderRadius: 3, cursor: 'pointer',
                border: `1px solid ${caFilter === key ? C.ac : C.bd}`,
                background: caFilter === key ? ALPHA.ac09 : 'transparent',
                color: caFilter === key ? C.ac : C.t3, fontWeight: caFilter === key ? 600 : 400,
              }}>{label}</button>
            ))}
            <input
              placeholder="Search CA or auditor…"
              value={caSearch}
              onChange={e => setCaSearch(e.target.value)}
              style={{
                marginLeft: 'auto', padding: '2px 8px', fontSize: 10, borderRadius: 3,
                border: `1px solid ${C.bd}`, background: C.s2, color: C.tx,
                outline: 'none', width: 'clamp(120px, 40vw, 160px)',
              }}
            />
          </div>
          {isMobile ? (
            /* Mobile: card per row */
            filteredRows.length === 0
              ? <div style={{ textAlign: 'center', fontSize: 12, color: C.t3, padding: '16px 0' }}>No matching results</div>
              : filteredRows.map((r, i) => {
                const TYPE_LABEL = { commercial: 'Commercial', government: 'Government', state_enterprise: 'State-Owned', non_profit: 'Non-Profit' };
                const TYPE_COLOR = { commercial: C.t2, government: C.rd, state_enterprise: C.am, non_profit: C.gn };
                const storeDots = ['mozilla','chrome','microsoft','apple'].map(k => {
                  const trusted = r.trustedStores.includes(k);
                  return <span key={k} style={{ width: 7, height: 7, borderRadius: '50%', display: 'inline-block', background: trusted ? STORE_COLORS[k] : C.bd, border: trusted ? 'none' : `1px solid ${C.bl}` }} />;
                });
                return (
                  <div key={r.ca} style={{ background: C.s2, borderRadius: 8, border: `1px solid ${C.bd}`, padding: '10px 12px', marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: C.tx, flex: 1, marginRight: 8 }}>{r.ca}</div>
                      <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>{storeDots}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
                      <span style={{ fontSize: 10, fontWeight: 600, color: TYPE_COLOR[r.caType] ?? C.t2 }}>{TYPE_LABEL[r.caType] ?? r.caType}</span>
                      {r.auditor !== 'Unknown' && <span style={{ fontSize: 10, color: C.t3 }}>{r.auditor}</span>}
                      {r.pass && <span style={{ fontSize: 10, color: C.gn, fontWeight: 600 }}>✓ Pass</span>}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: '6px 8px' }}>
                      {[
                        { label: 'Trusted roots absent', val: r.missingFps,      color: r.missingFps > 0 ? C.rd : C.t3,  bold: r.missingFps > 0 },
                        { label: 'Sub-CAs in letter',    val: r.subCaFps,         color: r.subCaFps > 0 ? C.t2 : C.t3 },
                        { label: 'Not in CCADB',         val: r.unregisteredFps,  color: r.unregisteredFps > 0 ? C.am : C.t3 },
                      ].map(({ label, val, color, bold }) => (
                        <div key={label}>
                          <div style={{ fontSize: 9, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 1 }}>{label}</div>
                          <div style={{ fontSize: 12, color, fontWeight: bold ? 600 : 400 }}>{val || '—'}</div>
                        </div>
                      ))}
                    </div>
                    {(r.scopeGaps.length > 0 || r.untracedRoots > 0) && (
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 8px', marginTop: 6 }}>
                        {r.scopeGaps.length > 0 && (
                          <div>
                            <div style={{ fontSize: 9, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 1 }}>Scope gaps</div>
                            <div style={{ fontSize: 11, color: C.am }}>{r.scopeGaps.join(', ')}</div>
                          </div>
                        )}
                        {r.untracedRoots > 0 && (
                          <div>
                            <div style={{ fontSize: 9, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 1 }}>No audit URL</div>
                            <div style={{ fontSize: 12, color: C.am }}>{r.untracedRoots}</div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
          ) : (
          <div style={scrollXStyle}>
          <table style={{ ...compactTableStyle, width: '100%' }}>
            <thead>
              <tr>
                {[
                  { col: 'ca',             label: 'CA',                        style: { ...thS, position: 'sticky', left: 0, background: 'var(--bg,#111)', zIndex: 2 } },
                  { col: 'stores',         label: 'Stores',                    style: thS },
                  { col: 'caType',         label: 'Type',                      style: thS },
                  { col: 'missingFps',        label: <>Trusted roots<br/>not in letter</>,       style: thR },
                  { col: 'scopeGaps',          label: 'Scope gaps',                style: thS },
                  { col: 'subCaFps',           label: <>Sub-CAs<br/>in letter</>,                style: thR },
                  { col: 'undisclosedFps',     label: <>Attested,<br/>not in CCADB</>,           style: thR },
                  { col: 'crossSignedMissing', label: <>Cross-signed<br/>missing (§5.1)</>,      style: thR },
                  { col: 'untraced',       label: <>No audit<br/>URL</>,                     style: thR },
                ].map(({ col, label, style }) => (
                  <th key={col} style={{ ...style, cursor: 'pointer', userSelect: 'none' }}
                      onClick={() => onSort(col)}>
                    {label}{sortArrow(col)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredRows.length === 0
                ? <tr><td colSpan={7} style={{ padding: '16px 10px', textAlign: 'center',
                    fontSize: 12, color: C.t3, borderBottom: `1px solid ${C.bd}` }}>
                    No matching results
                  </td></tr>
                : filteredRows.map((r, i) => {
                const TYPE_LABEL = {
                  commercial: 'Commercial', government: 'Government',
                  state_enterprise: 'State-Owned', non_profit: 'Non-Profit',

                };
                const TYPE_COLOR = {
                  commercial: C.t2, government: C.rd, state_enterprise: C.am,
                  non_profit: C.gn,
                };
                return (
                <tr key={a.auditor}>
                  <td style={{ padding: '6px 10px', fontSize: 12, color: C.tx,
                    borderBottom: `1px solid ${C.bd}`, fontWeight: 500,
                    position: 'sticky', left: 0, background: C.bg ?? '#111', zIndex: 1,
                    maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.ca.length > 28 ? r.ca.slice(0, 27) + '…' : r.ca}
                  </td>
                  <td style={{ padding: '6px 10px', borderBottom: `1px solid ${C.bd}` }}>
                    <span style={{ display: 'inline-flex', gap: 3 }}>
                      {[
                        { key: 'mozilla',   label: 'Mozilla',   color: STORE_COLORS.mozilla },
                        { key: 'chrome',    label: 'Chrome',    color: STORE_COLORS.chrome },
                        { key: 'microsoft', label: 'Microsoft', color: STORE_COLORS.microsoft },
                        { key: 'apple',     label: 'Apple',     color: STORE_COLORS.apple },
                      ].map(({ key, label, color }) => {
                        const trusted = r.trustedStores.includes(key);
                        return (
                          <span key={key} title={trusted ? `Trusted by ${label}` : `Not trusted by ${label}`}
                            style={{ width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
                              background: trusted ? color : C.bd,
                              border: trusted ? 'none' : `1px solid ${C.bl}` }} />
                        );
                      })}
                    </span>
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 10, borderBottom: `1px solid ${C.bd}`,
                    color: TYPE_COLOR[r.caType] ?? C.t2, fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {TYPE_LABEL[r.caType] ?? r.caType}
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                    textAlign: 'right', color: r.missingFps > 0 ? C.rd : C.t3, fontWeight: r.missingFps > 0 ? 600 : 400 }}>
                    {r.missingFps > 0 ? r.missingFps : '—'}
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 11, borderBottom: `1px solid ${C.bd}`,
                    color: r.scopeGaps.length > 0 ? C.am : C.t3 }}
                    title={r.scopeGapNote ?? undefined}>
                    {r.scopeGaps.length > 0 ? r.scopeGaps.join(', ') : '—'}
                    {r.scopeGapNote && r.scopeGaps.length > 0 &&
                      <span style={{ marginLeft: 4, fontSize: 9, color: C.t3, cursor: 'help' }}>ⓘ</span>
                    }
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                    textAlign: 'right', color: r.subCaFps > 0 ? C.t2 : C.t3 }}>
                    {r.subCaFps > 0 ? r.subCaFps : '—'}
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                    textAlign: 'right', color: r.unregisteredFps > 0 ? C.am : C.t3 }}>
                    {r.unregisteredFps > 0 ? r.unregisteredFps : '—'}
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                    textAlign: 'right', color: r.crossSignedMissing > 0 ? C.rd : C.t3,
                    fontWeight: r.crossSignedMissing > 0 ? 600 : 400 }}
                    title={r.crossSignedMissing > 0
                      ? `§5.1: ${r.crossSignedMissing} cross-signed certificate fingerprint${r.crossSignedMissing > 1 ? 's' : ''} this CA issued are absent from its audit letter`
                      : 'No active cross-signed certificates issued by this CA'}>
                    {r.crossSignedMissing > 0 ? r.crossSignedMissing : '—'}
                  </td>
                  <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                    textAlign: 'right', color: r.untracedRoots > 0 ? C.am : C.t3 }}>
                    {r.untracedRoots > 0 ? r.untracedRoots : '—'}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          </div>
          )}
        </>
      )}

      {/* By Auditor view */}
      {viewMode === 'auditor' && auditorRows.length > 0 && (
        isMobile ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {auditorRows.map((a, i) => {
              const sgPct = Math.round(a.scopeGap / a.total * 100);
              return (
                <div key={a.auditor} style={{ background: C.s2, borderRadius: 8, border: `1px solid ${C.bd}`, padding: '10px 12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: C.tx }}>{a.auditor}</div>
                    <div style={{ fontSize: 11, color: C.t3 }}>{a.total} CA{a.total !== 1 ? 's' : ''}</div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px 8px' }}>
                    {[
                      { label: 'Trusted roots absent', val: a.totalMissingRoots,    color: a.totalMissingRoots > 0 ? C.rd : C.t3, bold: a.totalMissingRoots > 0 },
                      { label: 'Sub-CAs in letter',    val: a.totalSubCaFps,         color: a.totalSubCaFps > 0 ? C.t2 : C.t3 },
                      { label: 'Not in CCADB',         val: a.totalUnregistered,     color: a.totalUnregistered > 0 ? C.am : C.t3 },
                      { label: 'Cross-signed missing', val: a.totalCrossSignedMiss,  color: a.totalCrossSignedMiss > 0 ? C.rd : C.t3, bold: a.totalCrossSignedMiss > 0 },
                      { label: 'Scope gaps',    val: a.scopeGap > 0 ? `${a.scopeGap}/${a.total}` : null, color: sgPct > 80 ? C.am : C.t2 },
                      { label: 'Pass',          val: a.pass > 0 ? `${a.pass}/${a.total}` : null, color: C.gn },
                    ].map(({ label, val, color, bold }) => (
                      <div key={label}>
                        <div style={{ fontSize: 9, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 1 }}>{label}</div>
                        <div style={{ fontSize: 12, color: val ? color : C.t3, fontWeight: bold ? 600 : 400 }}>{val || '—'}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
        <div style={scrollXStyle}>
          <table style={{ ...compactTableStyle, width: '100%' }}>
            <thead>
              <tr>
                <th style={{ ...thS, position: 'sticky', left: 0, background: 'var(--bg,#111)', zIndex: 2 }}>Auditor</th>
                <th style={thR}>Clients</th>
                <th style={thR}>Trusted roots<br/>not in letter</th>
                <th style={thR}>Scope gaps<br/><span style={{fontWeight:400,color:C.t3,fontSize:9}}># CAs</span></th>
                <th style={thR}>Sub-CAs<br/>in letter</th>
                <th style={thR}>Attested,<br/>not in CCADB</th>
                <th style={thR}>Cross-signed<br/>missing (§5.1)</th>
                <th style={thR}>Pass<br/><span style={{fontWeight:400,color:C.t3,fontSize:9}}># CAs</span></th>
              </tr>
            </thead>
            <tbody>
              {auditorRows.map((a, i) => {
                const sgPct = Math.round(a.scopeGap / a.total * 100);
                return (
                  <tr key={a.auditor}>
                    <td style={{ padding: '6px 10px', fontSize: 12, color: C.tx,
                      borderBottom: `1px solid ${C.bd}`, fontWeight: 500,
                      position: 'sticky', left: 0, background: C.bg ?? '#111', zIndex: 1 }}>
                      {a.auditor.length > 34 ? a.auditor.slice(0, 33) + '…' : a.auditor}
                    </td>
                    <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                      textAlign: 'right', color: C.t2 }}>{a.total}</td>
                    <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                      textAlign: 'right', color: a.totalMissingRoots > 0 ? C.rd : C.t3,
                      fontWeight: a.totalMissingRoots > 0 ? 600 : 400 }}>
                      {a.totalMissingRoots > 0 ? a.totalMissingRoots : '—'}
                    </td>
                    <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                      textAlign: 'right', color: sgPct > 80 ? C.am : a.scopeGap > 0 ? C.t2 : C.t3 }}>
                      {a.scopeGap > 0 ? `${a.scopeGap}/${a.total}` : '—'}
                    </td>
                    <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                      textAlign: 'right', color: a.totalSubCaFps > 0 ? C.t2 : C.t3 }}>
                      {a.totalSubCaFps > 0 ? a.totalSubCaFps : '—'}
                    </td>
                    <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                      textAlign: 'right', color: a.totalUnregistered > 0 ? C.am : C.t3 }}>
                      {a.totalUnregistered > 0 ? a.totalUnregistered : '—'}
                    </td>
                    <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                      textAlign: 'right', color: a.totalCrossSignedMiss > 0 ? C.rd : C.t3,
                      fontWeight: a.totalCrossSignedMiss > 0 ? 600 : 400 }}>
                      {a.totalCrossSignedMiss > 0 ? a.totalCrossSignedMiss : '—'}
                    </td>
                    <td style={{ padding: '6px 10px', fontSize: 12, borderBottom: `1px solid ${C.bd}`,
                      textAlign: 'right', color: a.pass > 0 ? C.gn : C.t3 }}>
                      {a.pass > 0 ? `${a.pass}/${a.total}` : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p style={{ fontSize: 11, color: C.t3, margin: '8px 0 0' }}>
            Auditors with 2+ parsed client letters shown. A 100% missing-fingerprints rate across
            all clients suggests the firm uses a letter template that omits fingerprint listings
            as standard practice, not a per-CA issue.
          </p>
        </div>
        )
      )}

      {viewMode === 'ca' && (
        <dl style={{ fontSize: 11, color: C.t3, margin: '10px 0 0', display: 'grid',
          gridTemplateColumns: 'max-content 1fr', gap: '3px 10px', lineHeight: 1.5 }}>
          <dt style={{ fontWeight: 600, color: C.t2, whiteSpace: 'nowrap' }}>Trusted roots not in letter</dt>
          <dd style={{ margin: 0 }}>TLS-capable root certificates in CCADB assigned to this letter's audit URL that the auditor did not enumerate — the core verifiability gap.</dd>
          <dt style={{ fontWeight: 600, color: C.t2, whiteSpace: 'nowrap' }}>Sub-CAs in letter</dt>
          <dd style={{ margin: 0 }}>Subordinate CA fingerprints the auditor enumerated that match CCADB Intermediate Certificate records — expected practice; shows the auditor covered the sub-CA hierarchy.</dd>
          <dt style={{ fontWeight: 600, color: C.t2, whiteSpace: 'nowrap' }}>Attested, not in CCADB</dt>
          <dd style={{ margin: 0 }}>Fingerprints in the letter matching no CCADB record — the auditor is attesting scope over certificates the ecosystem has never registered. Consistent with cross-certificates, eIDAS hierarchies, or undisclosed sub-CAs.</dd>
          <dt style={{ fontWeight: 600, color: C.t2, whiteSpace: 'nowrap' }}>Scope gaps</dt>
          <dd style={{ margin: 0 }}>Certificate types the CA is trusted to issue with no covering audit letter on file (TLS BR, separate filing, or combined letter). TLS DV and TLS OV are both covered by the single TLS BR document — they appear as separate gaps only when a non-standard criteria profile (e.g. ETSI NCP+OVCP, IMDA) covers one level but not the other. TLS EV, S/MIME, and Code Signing each require a dedicated separate letter.</dd>
          <dt style={{ fontWeight: 600, color: C.t2, whiteSpace: 'nowrap' }}>No audit URL</dt>
          <dd style={{ margin: 0 }}>CCADB root records for this CA owner with no audit URL filed anywhere — roots not assigned to any audit engagement.</dd>
          <dt style={{ fontWeight: 600, color: C.t2, whiteSpace: 'nowrap' }}>Cross-signed missing (§5.1)</dt>
          <dd style={{ margin: 0 }}>Active cross-signed certificate fingerprints this CA issued that are absent from its audit letter. Per CCADB Policy §5.1, the issuing CA's audit statement must enumerate certificates it cross-signed, even when the subject key belongs to a different CA owner. A count here is a direct §5.1 gap. "—" means this CA has no active cross-signed certificates outstanding.</dd>
        </dl>
      )}
    </Card>
  );
}

function QualityOverTime({ profiles }) {
  const [recentOnly, setRecentOnly] = useState(false); // default all — era context needs full range

  const activeProfiles = useMemo(() =>
    recentOnly
      ? profiles.filter(p => p.staleness === 'current' || p.staleness === 'aging')
      : profiles,
    [profiles, recentOnly]);

  const byYear = useMemo(() => {
    const map = {};
    activeProfiles.forEach(p => {
      const yr = (p.latest_stmt_date ?? '').slice(0, 4);
      const qs = p.letter_quality_score?.overall;
      if (!yr || qs == null) return;
      if (!map[yr]) map[yr] = { year: yr, scores: [], epoch: p.score_epoch };
      map[yr].scores.push(qs);
    });
    return Object.values(map).sort((a, b) => a.year.localeCompare(b.year))
      .map(d => ({ ...d, avg: Math.round(d.scores.reduce((a, b) => a + b, 0) / d.scores.length * 10) / 10, n: d.scores.length }));
  }, [activeProfiles]);

  if (!byYear.length) return <PdfPendingInline />;

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
        <CardTitle sub="Average letter quality score per year, each scored against the standard in effect at that time. Years are not directly comparable — earlier letters faced easier requirements. Color shows which era of audit rules applied.">
          Audit Letter Quality by Year and Audit Era
        </CardTitle>
        <InlineToggle value={recentOnly} onChange={setRecentOnly} />
      </div>
      <div style={{ display: 'flex', gap: 16, marginBottom: 8, fontSize: 11, color: C.t2 }}>
        {Object.entries(epochLabel).map(([k, l]) => (
          <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: EPOCH_COLORS[k], display: 'inline-block' }} />
            {l}
          </span>
        ))}
      </div>
      <div style={{ overflowX: 'auto' }}>
      <ChartWrap height={200} style={{ minWidth: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
        <BarChart data={byYear} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" stroke={C.bd} strokeOpacity={0.4} />
          <XAxis dataKey="year" tick={{ fontSize: 10, fill: C.t3 }} />
          <YAxis domain={[0, 105]} tick={{ fontSize: 10, fill: C.t3 }} width={28} />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload;
            return (
              <div style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 6,
                padding: '8px 12px', fontSize: 12 }}>
                <div style={{ fontWeight: 500 }}>{d.year}</div>
                <div style={{ color: C.t2 }}>Avg quality: <b style={{ color: C.tx }}>{fmt1(d.avg)}</b></div>
                <div style={{ color: C.t2 }}>Letters: <b style={{ color: C.tx }}>{d.n}</b></div>
              </div>
            );
          }} />
          <Bar dataKey="avg" radius={[3, 3, 0, 0]} maxBarSize={36}>
            {byYear.map(d => <Cell key={d.year} fill={EPOCH_COLORS[d.epoch] ?? C.ac} />)}
          </Bar>
        </BarChart>
        </ResponsiveContainer>
      </ChartWrap>
      </div>
    </Card>
  );
}

// ── CHART: ETSI AAL adoption ─────────────────────────────────────────────────
function EtsiAalChart({ profiles, insight }) {
  const data = useMemo(() => {
    const etsi = profiles.filter(p => p.primary_framework === 'ETSI' && p.pdf_parsed);
    if (!etsi.length) return null;
    const counts = { v35: 0, v34: 0, older: 0, none: 0 };
    etsi.forEach(p => {
      const aal = (p.criteria_check ?? {}).aal_version;
      if (!aal)       counts.none++;
      else if (aal === '3.5') counts.v35++;
      else if (aal === '3.4') counts.v34++;
      else             counts.older++;
    });
    return [
      { name: 'V3.5 (mandatory)', n: counts.v35,  col: C.gn },
      { name: 'V3.4 (outdated)',  n: counts.v34,  col: C.am },
      { name: 'Older',            n: counts.older, col: C.rd },
      { name: 'Not found',        n: counts.none,  col: C.g5 },
    ].filter(d => d.n > 0);
  }, [profiles]);

  if (!data) return <PdfPendingInline />;
  const total = data.reduce((s, d) => s + d.n, 0);

  // Compute v3.5 adoption count for dynamic title/subtitle
  const v35Count = data?.find(d => d.name.startsWith('V3.5'))?.n ?? 0;
  const v35Title = 'Which AAL template version are European CAs using?';
  const v35Sub = v35Count === 0
    ? `European CAs must use the AAL (Audit Attestation Letter) template. Version 3.5 became mandatory in March 2026, but none of the ${total} parsed ETSI letters have adopted it yet.`
    : `European CAs must use the AAL (Audit Attestation Letter) template. Version 3.5 became mandatory in March 2026. ${v35Count} of ${total} CAs are now compliant.`;

  return (
    <Card>
      <CardTitle sub={v35Sub}>
        {v35Title}
      </CardTitle>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
        {data.map(d => (
          <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 110, fontSize: 11, color: C.t2, flexShrink: 0 }}>{d.name}</div>
            <div style={{ flex: 1, height: 18, background: C.s2, borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${(d.n / total) * 100}%`, height: '100%', background: d.col,
                borderRadius: 3, minWidth: d.n > 0 ? 4 : 0 }} />
            </div>
            <div style={{ minWidth: 20, fontSize: 12, fontWeight: 500, color: C.tx }}>{d.n}</div>
          </div>
        ))}
      </div>
      {insight && (
        <p style={{ fontSize: 11, color: C.t2, margin: '8px 0 0', fontStyle: 'italic' }}>{insight}</p>
      )}
    </Card>
  );
}

// ── CHART+TABLE: Per-store posture ───────────────────────────────────────────
function StorePostureChart({ profiles }) {
  const stores = ['mozilla', 'chrome', 'apple', 'microsoft'];

  const rows = useMemo(() =>
    stores.map(s => {
      const sp     = profiles.filter(p => p.trusted_stores?.includes(s));
      const n      = sp.length;
      const parsed = sp.filter(p => p.pdf_parsed);
      const current = sp.filter(p => p.staleness === 'current').length;
      const aging   = sp.filter(p => p.staleness === 'aging').length;
      const stale   = sp.filter(p => p.staleness === 'stale').length;
      const vstale  = sp.filter(p => p.staleness === 'very_stale').length;
      const hg      = parsed.filter(p => effectiveTransparencyLevel(p) === 'low').length;
      const qual    = parsed.filter(p => p.opinion_type === 'qualified').length;
      const unaud   = sp.filter(p => (p.root_coverage?.roots_without_url ?? 0) > 0).length;

      // Missed incident exposure from retrospective
      let retroCovered = 0, retroCaught = 0, retroMissed = 0, retroMulti = 0;
      for (const p of sp) {
        for (const r of (p.bug_retrospective ?? [])) {
          if (r.covering_letters > 0) {
            retroCovered++;
            if (r.mentioned_in > 0) retroCaught++;
            else {
              retroMissed++;
              if (r.missed_by >= 2) retroMulti++;
            }
          }
        }
      }

      return {
        store: s, n,
        current, aging, stale, vstale,
        currentPct: Math.round(current / n * 100),
        agingPct:   Math.round(aging   / n * 100),
        stalePct:   Math.round(stale   / n * 100),
        vstalePct:  Math.round(vstale  / n * 100),
        hg, hgPct: parsed.length ? Math.round(hg / parsed.length * 100) : 0,
        parsedN: parsed.length,
        qual, unaud,
        retroMissed, retroMulti, retroCaught, retroCovered,
      };
    }), [profiles]);

  const dotS = s => ({ display: 'inline-block', width: 8, height: 8,
    borderRadius: '50%', background: STORE_COLORS[s] ?? C.g5, marginRight: 5 });

  const SectionLabel = ({ children, sub }) => (
    <div style={{ marginBottom: 8 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: C.t2 }}>{children}</span>
      {sub && <span style={{ fontSize: 10, color: C.t3, marginLeft: 6 }}>{sub}</span>}
    </div>
  );

  const StoreLabel = ({ store }) => (
    <div style={{ width: 80, fontSize: 11, color: C.t2, display: 'flex',
      alignItems: 'center', flexShrink: 0 }}>
      <span style={dotS(store)} />{store.charAt(0).toUpperCase() + store.slice(1)}
    </div>
  );

  return (
    <Card>
      <CardTitle sub="Each row is a browser trust store. Three views: how fresh the audit coverage is, how many CAs show low in-period transparency (few incidents from the current audit period mentioned in the letter), and how many incidents that fell inside an audit period went unmentioned.">
        Audit coverage and incident exposure by store
      </CardTitle>

      {/* Section 1: Coverage freshness */}
      <SectionLabel sub="What share of CAs have a current audit letter">Coverage freshness</SectionLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 6 }}>
        {rows.map(r => (
          <div key={r.store} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <StoreLabel store={r.store} />
            <div style={{ flex: 1, height: 16, display: 'flex', borderRadius: 3, overflow: 'hidden' }}>
              {[
                { val: r.currentPct, col: C.gn },
                { val: r.agingPct,   col: C.ac },
                { val: r.stalePct,   col: C.am },
                { val: r.vstalePct,  col: C.rd },
              ].map(({ val, col }, i) => val > 0 && (
                <div key={i} style={{ width: `${val}%`, background: col, height: '100%' }} />
              ))}
            </div>
            <div style={{ fontSize: 11, color: C.t2, minWidth: 80, textAlign: 'right' }}>
              {r.vstale > 0
                ? <span style={{ color: C.rd }}>{r.vstale} very stale</span>
                : <span style={{ color: C.gn }}>none very stale</span>
              }
              <span style={{ color: C.t3 }}> / {r.n}</span>
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: C.t2, marginBottom: 20 }}>
        {[
          ['Current',    C.gn, '<180 days'],
          ['Aging',      C.ac, '180–365 days'],
          ['Stale',      C.am, '1–2 years'],
          ['Very stale', C.rd, '>2 years'],
        ].map(([l, col, range]) => (
          <span key={l} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: col, display: 'inline-block' }} />
            {l}
            <span style={{ color: C.t3, marginLeft: 2 }}>{range}</span>
          </span>
        ))}
      </div>

      {/* Section 2: Transparency */}
      <SectionLabel sub="Share of CAs with low disclosure: fewer than 30% of incidents open during their current audit period mentioned in the letter. Where in-period data is unavailable, all-time citation rate is used as fallback.">
        CAs with low transparency
      </SectionLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
        {rows.map(r => (
          <div key={r.store} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <StoreLabel store={r.store} />
            <div style={{ flex: 1, height: 16, background: C.s2, borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${r.hgPct}%`, height: '100%', background: C.rd, opacity: 0.75, borderRadius: 3 }} />
            </div>
            <div style={{ fontSize: 11, minWidth: 80, textAlign: 'right' }}>
              <span style={{ color: C.rd, fontWeight: 500 }}>{r.hgPct}%</span>
              <span style={{ color: C.t3 }}> ({r.hg}/{r.parsedN})</span>
            </div>
          </div>
        ))}
      </div>

      {/* Section 3: Missed incident exposure */}
      {rows.some(r => r.retroCovered > 0) && (
        <>
          <SectionLabel sub="Incidents that fell inside an audit period but were not mentioned in the letter">
            Missed incident exposure
          </SectionLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
            {rows.map(r => {
              if (r.retroCovered === 0) return null;
              const maxMissed = Math.max(...rows.map(x => x.retroMissed), 1);
              return (
                <div key={r.store} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <StoreLabel store={r.store} />
                  <div style={{ flex: 1, height: 16, background: C.s2, borderRadius: 3,
                    overflow: 'hidden', position: 'relative' }}>
                    <div style={{ width: `${r.retroMissed / maxMissed * 100}%`,
                      height: '100%', background: C.rd, opacity: 0.6, borderRadius: 3 }} />
                    <div style={{ position: 'absolute', top: 0, left: 0,
                      width: `${r.retroMulti / maxMissed * 100}%`,
                      height: '100%', background: C.rd, borderRadius: 3 }} />
                  </div>
                  <div style={{ fontSize: 11, minWidth: 120, textAlign: 'right' }}>
                    <span style={{ color: C.rd, fontWeight: 500 }}>{r.retroMissed}</span>
                    <span style={{ color: C.t3 }}> missed</span>
                    {r.retroMulti > 0 && (
                      <span style={{ color: C.t3 }}>, {r.retroMulti} multi-cycle</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', gap: 14, fontSize: 10, color: C.t2, marginBottom: 8 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: C.rd, opacity: 0.6, display: 'inline-block' }} />
              Missed once
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: C.rd, display: 'inline-block' }} />
              Multi-cycle miss
            </span>
            <span style={{ color: C.t3 }}>Stores overlap — counts are not additive</span>
          </div>
        </>
      )}

      {/* Actionable signals — 4 cards in a row */}
      <div style={{ borderTop: `1px solid ${C.bd}`, paddingTop: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, textTransform: 'uppercase',
          letterSpacing: '0.05em', marginBottom: 8 }}>Actionable Signals</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {rows.map(r => (
            <div key={r.store} style={{ flex: '1 1 160px', padding: '8px 10px', borderRadius: 6,
              background: C.s2, border: `1px solid ${C.bd}`, minWidth: 140 }}>
              <div style={{ fontSize: 11, fontWeight: 500, color: C.t2, marginBottom: 6,
                display: 'flex', alignItems: 'center' }}>
                <span style={dotS(r.store)} />{r.store}
              </div>
              {[
                ['Missed in-scope incidents',    r.retroMissed, r.retroMissed > 0 ? C.rd : null],
                ['Multi-cycle misses',           r.retroMulti,  r.retroMulti  > 0 ? C.rd : null],
                ['Qualified opinions',           r.qual,        r.qual        > 0 ? C.am : null],
                ['Roots with no audit URL',      r.unaud,       r.unaud       > 0 ? C.am : null],
                ['Very stale (>18 months)',      r.vstale,      r.vstale      > 0 ? C.rd : null],
              ].map(([label, val, col]) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between',
                  fontSize: 11, color: C.t2, marginBottom: 3 }}>
                  <span style={{ color: C.t3 }}>{label}</span>
                  <span style={{ fontWeight: val > 0 ? 600 : 400,
                    color: col ?? (val === 0 ? C.t3 : C.tx) }}>{val}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

// ── CHART: Auditor market concentration ──────────────────────────────────────
function AuditorConcentration({ aggregates, summary }) {
  const hhi = summary?.auditor_hhi ?? 0;
  // Derive denominator from aggregates directly — self-consistent with table rows.
  // summary.named_auditor_count is close but can diverge; the sum of ca_count
  // across all auditor entries is always the exact denominator for the shares shown.
  const totalCAs = Object.values(aggregates).reduce((s, a) => s + (a.ca_count || 0), 0) || 1;

  const rows = useMemo(() => {
    return Object.entries(aggregates)
      .map(([name, a]) => ({
        name,
        clients: a.ca_count,
        share: Math.round(a.ca_count / totalCAs * 100),
        hhiContrib: Math.round((a.ca_count / totalCAs * 100) ** 2),
        country: a.auditor_country ?? '',
        avgScore: a.avg_quality_score != null ? Math.round(a.avg_quality_score) : null,
        fpPct: a.avg_fp_coverage != null ? Math.round(a.avg_fp_coverage) : null,
      }))
      .filter(r => r.clients >= 1)
      .sort((a, b) => b.clients - a.clients);
  }, [aggregates, totalCAs]);

  if (!rows.length) return null;

  const maxClients = rows[0]?.clients ?? 1;

  // HHI thresholds: <1500 unconcentrated, 1500-2500 moderate, >2500 highly concentrated
  const hhiColor = hhi < 1500 ? C.gn : hhi < 2500 ? C.am : C.rd;
  const hhiLabel = hhi < 1500 ? 'Unconcentrated' : hhi < 2500 ? 'Moderately concentrated' : 'Highly concentrated';

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <CardTitle sub="Number of currently-trusted CA owners audited by each firm. HHI (Herfindahl-Hirschman Index) measures market concentration — below 1500 is unconcentrated, 1500–2500 moderate, above 2500 highly concentrated. A single firm auditing a large share of CAs creates systemic risk if that firm's methodology has blind spots.">
          Auditor market concentration
        </CardTitle>
        <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 16 }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: hhiColor, fontFamily: FONT_MONO }}>{Math.round(hhi)}</div>
          <div style={{ fontSize: 10, color: hhiColor, fontWeight: 600 }}>HHI — {hhiLabel}</div>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {rows.map(r => (
          <div key={r.name} style={{ display: 'grid', gridTemplateColumns: 'minmax(100px,160px) 1fr 40px 44px', gap: 8, alignItems: 'center' }}>
            <div style={{ fontSize: 11, color: C.tx, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                 title={r.name + (r.country ? ` (${r.country})` : '')}>
              {r.name}
            </div>
            <div style={{ position: 'relative', height: 14, background: C.s2, borderRadius: 2, overflow: 'hidden' }}>
              <div style={{
                position: 'absolute', left: 0, top: 0, bottom: 0,
                width: `${(r.clients / maxClients) * 100}%`,
                background: r.share > 10 ? C.am : C.ac,
                borderRadius: 2, opacity: 0.7,
              }} />
              <div style={{ position: 'absolute', left: 6, top: 0, bottom: 0, display: 'flex', alignItems: 'center',
                fontSize: 10, color: C.tx, fontWeight: 500 }}>
                {r.clients} CA{r.clients !== 1 ? 's' : ''}
              </div>
            </div>
            <div style={{ fontSize: 10, color: C.t3, textAlign: 'right' }}>{r.share}%</div>
            <div style={{ fontSize: 10, color: r.avgScore != null ? (r.avgScore > 70 ? C.gn : r.avgScore > 50 ? C.am : C.rd) : C.t3,
              textAlign: 'right', fontWeight: r.avgScore != null ? 600 : 400 }}>
              {r.avgScore != null ? `${r.avgScore}` : '—'}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 10, color: C.t3 }}>
        <span>Bar = CA clients. Color amber if &gt;10% share.</span>
        <span style={{ marginLeft: 'auto' }}>Score = avg letter quality (0–100)</span>
      </div>
    </Card>
  );
}

// ── CHART: Auditor timeliness ─────────────────────────────────────────────────
function AuditorTimeliness({ profiles }) {
  const rows = useMemo(() => {
    const byAud = {};
    for (const p of profiles) {
      const aud = p.primary_auditor;
      if (!aud) continue;
      if (!byAud[aud]) byAud[aud] = { name: aud, onTime: 0, late: 0, cas: [] };
      const s = p.staleness;
      if (s === 'current' || s === 'aging') byAud[aud].onTime++;
      else byAud[aud].late++;
      byAud[aud].cas.push(p.ca_owner);
    }
    return Object.values(byAud)
      .filter(r => r.onTime + r.late >= 2)
      .map(r => {
        const total = r.onTime + r.late;
        return { ...r, total, latePct: Math.round(r.late / total * 100) };
      })
      .sort((a, b) => b.latePct - a.latePct || b.total - a.total);
  }, [profiles]);

  if (!rows.length) return null;

  const shorten = n => n.length > 26 ? n.slice(0, 25) + '…' : n;
  const displayRows = rows.map(r => ({ ...r, shortName: shorten(r.name) }));

  return (
    <Card>
      <CardTitle sub="For each audit firm with 2+ clients, what share of those clients have a current audit report on file vs. a stale or overdue one. A high late rate may reflect the firm's capacity, the client's preparation, or both.">
        Which audit firms have clients with overdue reports?
      </CardTitle>
      <div style={{ display: 'flex', gap: 14, marginBottom: 8, fontSize: 10, color: C.t2 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: C.gn, display: 'inline-block' }} />
          Current or aging (&lt;1 year)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: C.rd, display: 'inline-block' }} />
          Stale or very stale (&gt;1 year)
        </span>
      </div>
      <div style={{ overflowX: 'auto' }}>
      <ChartWrap height={Math.max(180, displayRows.length * 28 + 40)} style={{ minWidth: 340 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart layout="vertical" data={displayRows}
            margin={{ top: 4, right: 80, bottom: 4, left: 160 }}>
            <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke={C.bd} strokeOpacity={0.4} />
            <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`}
              tick={{ fontSize: 10, fill: C.t3 }} />
            <YAxis type="category" dataKey="shortName" width={150}
              tick={{ fontSize: 11, fill: C.t2 }} />
            <Tooltip content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0]?.payload;
              return (
                <div style={{ background: C.s1, border: `1px solid ${C.bd}`, borderRadius: 6,
                  padding: '8px 12px', fontSize: 12 }}>
                  <div style={{ fontWeight: 500, marginBottom: 4 }}>{d.name}</div>
                  <div style={{ color: C.gn }}>Current/aging: <b>{d.onTime}</b></div>
                  <div style={{ color: C.rd }}>Stale/very stale: <b>{d.late}</b></div>
                  <div style={{ color: C.t2, marginTop: 4 }}>
                    {d.latePct}% of clients have overdue reports
                  </div>
                </div>
              );
            }} />
            <Bar dataKey="onTime" stackId="a" fill={C.gn} maxBarSize={18} />
            <Bar dataKey="late"   stackId="a" fill={C.rd} maxBarSize={18} radius={[0, 3, 3, 0]}>
              <LabelList dataKey="latePct" position="right" fontSize={10} fill={C.t3}
                formatter={v => v > 0 ? `${v}% late` : ''} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartWrap>
      </div>
      <p style={{ fontSize: 11, color: C.t3, margin: '8px 0 0' }}>
        Staleness reflects days since the audit period end date, not the report issue date.
        A stale report may reflect the CA, the auditor, or both.
        Only firms with 2+ clients in this dataset shown.
      </p>
    </Card>
  );
}


function RecentChangesTable({ profiles, aggregates }) {
  const currentYear = new Date().getFullYear();
  const [sinceYear, setSinceYear] = useState(currentYear - 1);

  // Recalculate availableYears from actual data — used only for the dropdown options
  const availableYears = useMemo(() => {
    const yrs = new Set();
    profiles.forEach(p =>
      (p.timeline_trends?.auditor_changes ?? []).forEach(c => yrs.add(c.year))
    );
    return Array.from(yrs).sort((a, b) => b - a);
  }, [profiles]);

  const allChanges = useMemo(() =>
    profiles
      .flatMap(p => (p.timeline_trends?.auditor_changes ?? [])
        .map(c => {
          const fromAgg = aggregates[c.from_auditor] ?? {};
          const toAgg   = aggregates[c.to_auditor]   ?? {};
          const fromQ   = fromAgg.avg_quality_score ?? null;
          const toQ     = toAgg.avg_quality_score   ?? null;
          const fromN   = fromAgg.parsed_count       ?? null;
          const toN     = toAgg.parsed_count         ?? null;
          const delta   = (fromQ != null && toQ != null) ? Math.round(toQ - fromQ) : null;
          const dir     = delta == null ? null
            : delta > 5  ? 'improvement'
            : delta < -5 ? 'decline'
            : 'neutral';
          // Confidence: based on how many parsed letters back the incoming firm's score
          const confidence = toN == null ? null
            : toN >= 5 ? 'high'
            : toN >= 2 ? 'moderate'
            : 'low';
          return {
            ca: p.ca_owner, year: c.year,
            from: c.from_auditor, to: c.to_auditor,
            fromQ, toQ, fromN, toN, delta, dir, confidence,
          };
        }))
      .sort((a, b) => {
        const rank = { decline: 0, neutral: 1, improvement: 2, null: 3 };
        const dirCompare = (rank[a.dir] ?? 3) - (rank[b.dir] ?? 3);
        if (dirCompare !== 0) return dirCompare;
        // Same direction: group by CA so round-trips appear together
        const caCompare = a.ca.localeCompare(b.ca);
        if (caCompare !== 0) return caCompare;
        return a.year - b.year;
      }),
    [profiles, aggregates]);

  const changes = useMemo(() =>
    allChanges.filter(c => c.year >= sinceYear),
    [allChanges, sinceYear]);

  if (!allChanges.length) return null;

  const improvements = changes.filter(c => c.dir === 'improvement').length;
  const declines     = changes.filter(c => c.dir === 'decline').length;
  const noData       = changes.filter(c => c.dir === null).length;
  const neutral      = changes.filter(c => c.dir === 'neutral').length;

  // Separate scorable from unscored rows
  const scorable   = changes.filter(c => c.dir !== null);
  const unscored   = changes.filter(c => c.dir === null);

  const confColor  = conf => conf === 'high' ? C.gn : conf === 'moderate' ? C.am : C.rd;
  const confLabel  = conf => conf === 'high' ? 'high confidence' : conf === 'moderate' ? 'moderate confidence' : 'low confidence';
  const confTip    = (conf, toN) => {
    if (conf === 'high')     return `Based on ${toN} parsed letters — firm has a meaningful track record in the WebPKI ecosystem`;
    if (conf === 'moderate') return `Based on ${toN} parsed letters — limited track record, treat estimate with caution`;
    return `Based on only ${toN} parsed letter — this firm has minimal track record in the WebPKI ecosystem; score may not be representative`;
  };

  const ImpactBadge = ({ dir, delta, confidence, toN, fromQ, toQ }) => {
    if (dir === null) return (
      <span style={{ fontSize: 11, color: C.t3, fontStyle: 'italic' }}>Insufficient data</span>
    );
    const cfg = {
      improvement: { color: C.gn },
      decline:     { color: C.rd },
      neutral:     { color: C.t3 },
    }[dir];
    const tip = toN != null
      ? confTip(confidence, toN)
      : 'No parsed letters from the incoming auditor yet';
    const dirLabel = dir === 'improvement' ? 'Incoming firm scores higher'
                   : dir === 'decline'     ? 'Incoming firm scores lower'
                   : 'Roughly neutral';
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: cfg.color }}>
          {dirLabel}
        </span>
        {fromQ != null && toQ != null && (
          <span style={{ fontSize: 11, color: C.t2 }}>
            {Math.round(fromQ)} → {Math.round(toQ)}
            <span style={{ color: C.t3, marginLeft: 4 }}>
              ({delta > 0 ? '+' : ''}{delta} pts on 0–100 letter quality scale)
            </span>
          </span>
        )}
        {confidence && (
          <span style={{ fontSize: 10, color: confColor(confidence) }} title={tip}>
            Based on {toN} letter{toN !== 1 ? 's' : ''} from incoming firm · {confLabel(confidence)}
          </span>
        )}
      </div>
    );
  };

  const AuditorCell = ({ name, score, n }) => (
    <div>
      <div style={{ fontSize: 12, color: C.tx }}>
        {name ? (name.length > 24 ? name.slice(0, 23) + '…' : name) : '—'}
      </div>
      {score != null && (
        <div style={{ fontSize: 10, color: C.t3, marginTop: 1 }}>
          Avg letter quality: {Math.round(score)}/100
          {n != null && <span> · {n} client{n !== 1 ? 's' : ''}</span>}
        </div>
      )}
    </div>
  );

  const tdS  = { padding: '8px 10px', borderBottom: `1px solid ${C.bd}`, verticalAlign: 'top' };
  const thS  = { padding: '6px 10px', fontSize: 10, fontWeight: 600, color: C.t3,
    borderBottom: `1px solid ${C.bd}`, textAlign: 'left', textTransform: 'uppercase',
    letterSpacing: '0.04em', whiteSpace: 'nowrap' };

  const SummaryChip = ({ value, label, color }) => (
    <div style={{ padding: '8px 14px', borderRadius: 6, background: C.s2,
      border: `1px solid ${C.bd}`, textAlign: 'center', minWidth: 100 }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: color ?? C.tx }}>{value}</div>
      <div style={{ fontSize: 11, color: C.t2, marginTop: 2 }}>{label}</div>
    </div>
  );

  return (
    <>
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <CardTitle sub="When a CA switches audit firms, the new firm's track record across its other WebPKI clients predicts whether letter quality will improve or decline. Each row compares the incoming firm's average letter-quality score (0–100) against the outgoing firm's average. This is a directional signal based on letter quality as a document — not a judgment on audit thoroughness.">
          Letter quality before and after auditor switches
        </CardTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{ fontSize: 10, color: C.t3 }}>Since</span>
          <select value={sinceYear} onChange={e => setSinceYear(Number(e.target.value))}
            style={{ fontSize: 11, padding: '2px 6px', borderRadius: 4, border: `1px solid ${C.bd}`,
              background: C.s1, color: C.t2, cursor: 'pointer' }}>
            {availableYears.map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Summary chips */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <SummaryChip value={improvements} label="Incoming scores higher" color={improvements > 0 ? C.gn : C.t3} />
        <SummaryChip value={declines}     label="Incoming scores lower"  color={declines > 0 ? C.rd : C.t3} />
        {neutral > 0 && <SummaryChip value={neutral} label="Neutral moves"      color={C.t3} />}
        {noData > 0 &&  <SummaryChip value={noData}  label="Insufficient data"  color={C.t3} />}
      </div>

      {/* Scorable rows */}
      {scorable.length > 0 && (
        <div style={scrollXStyle}>
          <table style={{ ...compactTableStyle, width: '100%' }}>
            <thead>
              <tr>
                <th style={thS}>CA</th>
                <th style={thS}>Previous auditor</th>
                <th style={thS}>New auditor</th>
                <th style={{ ...thS }}
                  title="Estimated impact = difference between new and previous auditor's avg letter-quality score across their other current clients (0–100 scale).">
                  Estimated impact ⓘ
                </th>
              </tr>
            </thead>
            <tbody>
              {scorable.slice(0, 25).map((c, i, arr) => {
                const caCount = arr.filter(x => x.ca === c.ca).length;
                const caIdx   = arr.slice(0, i).filter(x => x.ca === c.ca).length;
                return (
                <tr key={`${c.ca}-${c.year}`} style={{
                  background: c.dir === 'decline' ? ALPHA.rd04 : 'transparent',
                  borderTop: caIdx === 0 && i > 0 && arr[i-1].ca !== c.ca ? `1px solid ${C.bd}` : undefined,
                }}>
                  <td style={{ ...tdS, fontWeight: 600, color: C.tx, fontSize: 13 }}>
                    {c.ca.length > 34 ? c.ca.slice(0, 33) + '…' : c.ca}
                    <div style={{ fontSize: 10, color: C.t3, fontWeight: 400, marginTop: 1 }}>
                      {c.year}
                      {caCount > 1 && (
                        <span style={{ marginLeft: 6, color: C.am }}>
                          change {caIdx + 1} of {caCount}
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={{ ...tdS, color: C.t2 }}>
                    <AuditorCell name={c.from} score={c.fromQ} n={c.fromN} />
                  </td>
                  <td style={tdS}>
                    <AuditorCell name={c.to} score={c.toQ} n={c.toN} />
                  </td>
                  <td style={tdS}>
                    <ImpactBadge dir={c.dir} delta={c.delta} confidence={c.confidence} toN={c.toN} fromQ={c.fromQ} toQ={c.toQ} />
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p style={{ fontSize: 11, color: C.t3, margin: '12px 0 0' }}>
        Firm scores are average letter-quality scores (0–100) across their other current clients.
        Estimated impact is the difference between the new and previous firm averages.
        Confidence reflects how many parsed letters back the incoming firm's score.
      </p>
    </Card>

    {/* Separate card for unscored switches — no signal, different job */}
    {unscored.length > 0 && (
      <Card style={{ marginTop: 12, opacity: 0.8 }}>
        <CardTitle sub="The incoming auditor has no parsed letters in the WebPKI ecosystem — no track record to evaluate. This does not mean the switch is bad, but there is no basis for a quality prediction. These are worth monitoring as their first letters are issued.">
          Switches to auditors new to the ecosystem
        </CardTitle>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {unscored.map((c, i) => (
            <div key={`${c.ca}-${c.newAuditor || i}`} style={{ display: 'flex', alignItems: 'center', gap: 12,
              flexWrap: 'wrap', padding: '5px 8px', borderRadius: 4,
              borderLeft: `2px solid ${C.bd}` }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: C.tx, minWidth: 160 }}>
                {c.ca.length > 30 ? c.ca.slice(0, 29) + '…' : c.ca}
              </span>
              <span style={{ fontSize: 10, color: C.t3 }}>{c.year}</span>
              <span style={{ fontSize: 11, color: C.t2 }}>
                {c.from ?? '—'}
                {c.fromQ != null && <span style={{ color: C.t3 }}> ({Math.round(c.fromQ)})</span>}
                <span style={{ color: C.t3, margin: '0 6px' }}>→</span>
                {c.to ?? '—'}
              </span>
            </div>
          ))}
        </div>
      </Card>
    )}
    </>
  );
}

// ── TABLE: CA profiles ───────────────────────────────────────────────────────
function CATable({ profiles }) {
  const [search, setSearch]     = useState('');
  const [sortKey, setSortKey]   = useState('incident_count');
  const [sortDir, setSortDir]   = useState(-1);
  const [expanded, setExpanded] = useState(null);
  const [showStale, setShowStale] = useState(false);

  const getValue = (p, key) => {
    if (key === 'gap_score') return p.transparency_gap?.gap_score;
    if (key === 'quality')   return p.letter_quality_score?.overall;
    return p[key];
  };

  const staleCount = profiles.filter(p =>
    p.staleness === 'stale' || p.staleness === 'very_stale').length;

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return profiles
      .filter(p => {
        if (!showStale && (p.staleness === 'stale' || p.staleness === 'very_stale')) return false;
        return !q || p.ca_owner.toLowerCase().includes(q) ||
               (p.primary_auditor ?? '').toLowerCase().includes(q);
      })
      .sort((a, b) => {
        const av = getValue(a, sortKey), bv = getValue(b, sortKey);
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === 'string') return sortDir * av.localeCompare(bv);
        return sortDir * (av > bv ? 1 : -1);
      });
  }, [profiles, search, sortKey, sortDir, showStale]);

  const th = (label, key) => (
    <th onClick={() => { setSortKey(key); setSortDir(k => key === sortKey ? -k : -1); }}
      style={{ padding: '6px 10px', fontSize: 11, fontWeight: 500, color: C.t2,
        borderBottom: `1px solid ${C.bd}`, textAlign: 'left', cursor: 'pointer',
        userSelect: 'none', whiteSpace: 'nowrap' }}>
      {label}{sortKey === key ? (sortDir > 0 ? ' ↑' : ' ↓') : ''}
    </th>
  );
  const thS = { padding: '6px 10px', fontSize: 11, fontWeight: 500, color: C.t2,
    borderBottom: `1px solid ${C.bd}`, textAlign: 'left', whiteSpace: 'nowrap' };
  const tdS = { padding: '6px 10px', fontSize: 12, color: C.tx, borderBottom: `1px solid ${C.bd}` };

  return (
    <Card>
      <div style={{ ...controlRowStyle, marginBottom: 12 }}>
        <CardTitle sub="One row per CA. Click any row to see the audit letter details, per-letter incident coverage, and the retrospective showing which incidents fell inside each audit period and whether the letter mentioned them.">CA Audit Letter Quality</CardTitle>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {staleCount > 0 && (
            <button onClick={() => setShowStale(s => !s)}
              style={{ fontSize: 11, padding: '3px 10px', borderRadius: 4, cursor: 'pointer',
                border: `1px solid ${C.bd}`, background: showStale ? ALPHA.am13 : 'transparent',
                color: showStale ? C.am : C.t3 }}>
              {showStale ? `Hiding ${staleCount} stale` : `+ ${staleCount} stale`}
            </button>
          )}
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search CA or auditor…"
            style={{ fontSize: 12, padding: '4px 10px', borderRadius: 6,
              border: `1px solid ${C.bd}`, background: C.s1, color: C.tx, outline: 'none', width: 'clamp(140px, 50vw, 200px)' }} />
        </div>
      </div>
      <div style={{ fontSize: 11, color: C.t3, marginBottom: 10, lineHeight: 1.6,
        padding: '7px 10px', background: C.s2, borderRadius: 5, border: `1px solid ${C.bd}` }}>
        <b style={{ color: C.t2 }}>Columns use different scopes —</b>{' '}
        "Audit report quality" scores the current letter as a document.
        "Disclosure gap (all-time)" compares the CA's entire Bugzilla history against the current letter only.
        "Incidents (all-time)" is a lifetime count regardless of audit period timing.
        For in-period detection — which incidents were open during each audit and were they mentioned — expand a row.
      </div>
      <div style={scrollXStyle}>
        <table style={{ ...compactTableStyle, width: '100%' }}>
          <thead>
            <tr>
              {th('CA', 'ca_owner')}
              {th('Audit report quality', 'quality')}
              <th style={{ ...thS, cursor: 'help' }}
                title="Disclosure gap: fraction of this CA's all-time public compliance incident history that is absent from their current audit report. Different from in-period detection rate — this compares all-time Bugzilla history against the current letter only.">
                Disclosure gap (all-time) ⓘ
              </th>
              <th style={thS}>Audit standard era</th>
              <th style={{ ...thS, cursor: 'help' }}
                title="All Bugzilla compliance incidents ever filed for this CA — not filtered by date or audit period. Click to sort."
                onClick={() => { setSortKey('incident_count'); setSortDir(k => 'incident_count' === sortKey ? -k : -1); }}>
                Incidents (all-time){sortKey === 'incident_count' ? (sortDir > 0 ? ' ↑' : ' ↓') : ''}
              </th>
              {th('CA self-reported', 'self_report_pct')}
              <th style={thS}>Audit framework</th>
              <th style={thS}>Audit firm</th>
              <th style={thS}>Browser stores</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(p => {
              const qs  = p.letter_quality_score?.overall;
              const tg  = p.transparency_gap ?? {};
              const txLevel = effectiveTransparencyLevel(p);
              const isX = expanded === p.ca_owner;
              return (
                <React.Fragment key={p.ca_owner}>
                  <tr style={{ cursor: 'pointer', background: isX ? C.s2 : 'transparent' }}
                    onClick={() => setExpanded(isX ? null : p.ca_owner)}>
                    <td style={{ ...tdS, fontWeight: 500, whiteSpace: 'nowrap' }}>
                      <span style={{ marginRight: 4, fontSize: 10, color: C.t3 }}>
                        {isX ? '▼' : '▶'}
                      </span>
                      {p.ca_owner.length > 32 ? p.ca_owner.slice(0, 31) + '…' : p.ca_owner}
                    </td>
                    <td style={tdS}><ScoreBar value={qs} /></td>
                    <td style={tdS}><GapBadge level={txLevel} /></td>
                    <td style={tdS}><EpochBadge epoch={p.score_epoch} /></td>
                    <td style={{ ...tdS, textAlign: 'right' }}>{p.incident_count ?? '—'}</td>
                    <td style={{ ...tdS, textAlign: 'right' }}>
                      {p.self_report_pct != null ? `${Math.round(p.self_report_pct)}%` : '—'}
                    </td>
                    <td style={{ ...tdS, color: p.primary_framework === 'WebTrust' ? C.ac : C.pu }}>
                      {p.primary_framework ?? '—'}
                    </td>
                    <td style={{ ...tdS, color: C.t2, fontSize: 11 }}>
                      {p.primary_auditor ? (p.primary_auditor.length > 22 ? p.primary_auditor.slice(0, 21) + '…' : p.primary_auditor) : '—'}
                    </td>
                    <td style={tdS}>
                      <div style={{ display: 'flex', gap: 3 }}>
                        {(p.trusted_stores ?? []).map(s => (
                          <span key={s} style={{ width: 8, height: 8, borderRadius: '50%',
                            background: STORE_COLORS[s] ?? C.g5 }} title={s} />
                        ))}
                      </div>
                    </td>
                  </tr>
                  {isX && (
                    <tr>
                      <td colSpan={8} style={{ padding: '0 10px 12px', background: C.s2,
                        borderBottom: `1px solid ${C.bd}`, minWidth: 0, overflow: 'hidden' }}>
                        <CADetailPanel profile={p} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 11, color: C.t3, margin: '8px 0 0' }}>
        {filtered.length} CA{filtered.length !== 1 ? 's' : ''} shown. Click any row to expand audit detail and incident retrospective.
      </p>
    </Card>
  );
}

// ── BUG RETROSPECTIVE ────────────────────────────────────────────────────────
function BugRetrospective({ bugs }) {
  const [expandedLetters, setExpandedLetters] = useState(new Set());
  const [showMentioned, setShowMentioned] = useState({});

  // Group bugs by letter (stmt_date), building the hierarchical view
  const letters = useMemo(() => {
    const byKey = {};
    for (const r of bugs) {
      for (const c of (r.audit_coverage ?? [])) {
        const key = c.stmt_date ?? '—';
        if (!byKey[key]) byKey[key] = {
          stmt_date:    c.stmt_date,
          period_start: c.period_start,
          period_end:   c.period_end,
          mentioned: [], notMentioned: [],
        };
        const entry = {
          id:           r.id,
          filed:        r.filed,
          summary:      r.summary,
          self_reported: r.self_reported,
          missed_by:    r.missed_by,
        };
        if (c.mentioned) byKey[key].mentioned.push(entry);
        else             byKey[key].notMentioned.push(entry);
      }
    }
    return Object.values(byKey)
      .sort((a, b) => (b.stmt_date ?? '').localeCompare(a.stmt_date ?? ''))
      .map(lt => ({
        ...lt,
        notMentioned: [...lt.notMentioned].sort((a, b) => (b.missed_by ?? 0) - (a.missed_by ?? 0)),
      }));
  }, [bugs]);

  if (!letters.length) return null;

  const toggleLetter = key => setExpandedLetters(prev => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  const multiCycleTotal = bugs.filter(r => r.missed_by >= 2).length;
  const neverMentioned  = bugs.filter(r => r.mentioned_in === 0 && r.covering_letters > 0).length;

  // Tooltip explaining "in-scope"
  const inScopeTip = 'In-scope incidents are those whose Bugzilla filing date falls within the covered audit period. Filing date is used as a floor for when an issue entered the public record — the actual defect may have started earlier.';

  return (
    <div style={{ marginTop: 16, borderTop: `1px solid ${C.bd}`, paddingTop: 14,
      overflow: 'hidden', minWidth: 0 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t3,
        textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
        Incident disclosure coverage by audit letter
      </div>

      <div style={{ fontSize: 12, color: C.t2, marginBottom: 12, lineHeight: 1.6 }}>
        Each audit letter is shown with the incidents that were{' '}
        <span style={{ borderBottom: `1px dotted ${C.t3}`, cursor: 'help' }} title={inScopeTip}>
          in scope
        </span>
        {' '}during its coverage period — incidents filed while that audit period was active.
        {neverMentioned > 0 && (
          <span style={{ color: C.rd }}>
            {' '}<b>{neverMentioned}</b> in-scope incident{neverMentioned !== 1 ? 's were' : ' was'} never
            mentioned in any audit report.
          </span>
        )}
        {multiCycleTotal > 0 && (
          <span style={{ color: C.rd }}>
            {' '}<b>{multiCycleTotal}</b> persisted across multiple consecutive audit cycles without
            appearing in any audit report.
          </span>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {letters.map(lt => {
          const key     = lt.stmt_date ?? '—';
          const isOpen  = expandedLetters.has(key);
          const total   = lt.mentioned.length + lt.notMentioned.length;
          const pct     = total > 0 ? Math.round(lt.mentioned.length / total * 100) : 0;
          const barCol  = pct >= 70 ? C.gn : pct >= 30 ? C.am : C.rd;
          const showingMentioned = showMentioned[key];

          return (
            <div key={key} style={{ border: `1px solid ${C.bd}`, borderRadius: 6, overflow: 'hidden' }}>

              {/* Letter header — always visible, click to expand */}
              <div onClick={() => toggleLetter(key)}
                style={{ display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 12px', cursor: 'pointer',
                  background: isOpen ? C.s2 : C.bg,
                  borderBottom: isOpen ? `1px solid ${C.bd}` : 'none' }}>

                <span style={{ fontSize: 11, color: C.t3, flexShrink: 0 }}>
                  {isOpen ? '▼' : '▶'}
                </span>

                {/* Coverage period */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: C.tx }}>
                    <span style={{ fontSize: 10, color: C.t3, marginRight: 6 }}>Coverage period</span>
                    <span style={{ fontFamily: FONT_MONO }}>
                      {lt.period_start?.slice(0,7)} → {lt.period_end?.slice(0,7)}
                    </span>
                    <span style={{ color: C.t3, fontSize: 11, marginLeft: 8 }}>
                      report issued {lt.stmt_date?.slice(0,7)}
                    </span>
                  </div>
                </div>

                {/* Detection summary — fraction + bar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                  {total > 0 ? (
                    <>
                      <div style={{ width: 56, height: 6, background: C.s2,
                        borderRadius: 3, border: `1px solid ${C.bd}`, overflow: 'hidden' }}>
                        <div style={{ width: `${pct}%`, height: '100%',
                          background: barCol, borderRadius: 3 }} />
                      </div>
                      <span style={{ fontSize: 11, fontWeight: 600, color: barCol, minWidth: 44, textAlign: 'right' }}>
                        {lt.mentioned.length}/{total}
                      </span>
                      <span style={{ fontSize: 10, color: C.t3, minWidth: 48 }}>
                        mentioned
                      </span>
                    </>
                  ) : (
                    <span style={{ fontSize: 11, color: C.t3 }}>no in-scope incidents</span>
                  )}
                </div>
              </div>

              {/* Expanded: incidents under this letter */}
              {isOpen && (
                <div style={{ padding: '8px 12px' }}>

                  {/* Not mentioned — shown first, they're the finding */}
                  {lt.notMentioned.length > 0 && (
                    <div style={{ marginBottom: lt.mentioned.length > 0 ? 10 : 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 500, color: C.rd, marginBottom: 6 }}>
                        Not in audit report ({lt.notMentioned.length})
                      </div>
                      {lt.notMentioned.map(b => (
                        <RetroIncidentRow key={b.id} bug={b} status="missed" />
                      ))}
                    </div>
                  )}

                  {/* Mentioned — secondary, collapsible */}
                  {lt.mentioned.length > 0 && (
                    <div>
                      <button onClick={e => { e.stopPropagation(); setShowMentioned(s => ({ ...s, [key]: !s[key] })); }}
                        style={{ fontSize: 11, color: C.gn, background: 'none', border: 'none',
                          cursor: 'pointer', padding: 0, marginBottom: showingMentioned ? 6 : 0,
                          display: 'flex', alignItems: 'center', gap: 4 }}>
                        {showingMentioned ? '▼' : '▶'}
                        {' '}In audit report ({lt.mentioned.length})
                      </button>
                      {showingMentioned && lt.mentioned.map(b => (
                        <RetroIncidentRow key={b.id} bug={b} status="caught" />
                      ))}
                    </div>
                  )}

                  {lt.notMentioned.length === 0 && lt.mentioned.length === 0 && (
                    <div style={{ fontSize: 11, color: C.t3 }}>No in-scope incidents for this period.</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ fontSize: 11, color: C.t3, marginTop: 10, fontStyle: 'italic' }}>
        Filing date is used as a floor for when an issue entered the public record —
        the actual defect may have started earlier. Incidents outside all known audit periods are not shown here.
      </div>
    </div>
  );
}

function RetroIncidentRow({ bug, status }) {
  const isMissed  = status === 'missed';
  const isMulti   = bug.missed_by >= 2;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0,
      padding: '4px 6px', borderRadius: 4, marginBottom: 3,
      background: isMissed ? (isMulti ? ALPHA.rd08 : ALPHA.rd04) : ALPHA.gn04,
      border: `1px solid ${isMissed ? (isMulti ? ALPHA.rd25 : ALPHA.rd13) : ALPHA.gn20}` }}>
      <span style={{ fontSize: 11, color: isMissed ? C.rd : C.gn, flexShrink: 0 }}>
        {isMissed ? '✗' : '✓'}
      </span>
      <a href={`https://bugzilla.mozilla.org/show_bug.cgi?id=${bug.id}`}
        target="_blank" rel="noopener noreferrer"
        style={{ fontSize: 11, color: C.ac, textDecoration: 'none',
          fontFamily: FONT_MONO, flexShrink: 0 }}>
        #{bug.id}
      </a>
      <span style={{ fontSize: 10, color: C.t3, flexShrink: 0 }}>{bug.filed}</span>
      <span style={{ fontSize: 11, color: C.tx, overflow: 'hidden',
        textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
        {bug.summary.replace(/^[^:]+:\s*/, '')}
      </span>
      <div style={{ display: 'flex', gap: 6, flexShrink: 0, alignItems: 'center' }}>
        {isMulti && (
          <span style={{ fontSize: 10, color: C.rd, fontWeight: 600, whiteSpace: 'nowrap' }}>
            {bug.missed_by}× missed
          </span>
        )}
        <span style={{ fontSize: 10, color: C.t3 }}>
          {bug.self_reported ? 'self-reported' : 'externally found'}
        </span>
      </div>
    </div>
  );
}

// ── CA detail panel ───────────────────────────────────────────────────────────
function CADetailPanel({ profile: p }) {
  const tg     = p.transparency_gap ?? {};
  const qs     = p.letter_quality_score ?? {};
  const crit   = p.criteria_check ?? {};
  const rc     = p.root_coverage  ?? {};
  const trends = p.timeline_trends ?? {};

  const dimLabels = {
    opinion_clarity:        { l: 'Pass/fail conclusion clearly stated', tip: 'Did the audit report unambiguously state whether the CA passed or failed?' },
    criteria_currency:      { l: 'Audit standard was current',         tip: 'Was the audit conducted against the version of the standard required at the time?' },
    template_compliance:    { l: 'Required report template used',      tip: 'ETSI only: did the report use the required AAL template version? V3.4 required 2022–Mar 2026; V3.5 from Mar 2026.' },
    disclosure_completeness:{ l: 'Known incidents cross-referenced',   tip: 'Did the report explicitly cite compliance incidents that were open during the audit period?' },
    scope_coverage:         { l: "Audit scope matches CA's activity",  tip: "Does the audit cover all certificate types this CA actually issues?" },
  };

  // Per-letter incident summary
  const retro = p.bug_retrospective ?? [];
  const byLetter = {};
  for (const r of retro) {
    for (const c of (r.audit_coverage ?? [])) {
      const key = c.stmt_date ?? '—';
      if (!byLetter[key]) byLetter[key] = {
        stmt_date: c.stmt_date, period_start: c.period_start, period_end: c.period_end,
        mentioned: [], notMentioned: [],
      };
      if (c.mentioned) byLetter[key].mentioned.push(r.id);
      else byLetter[key].notMentioned.push(r.id);
    }
  }
  const letterRows = Object.values(byLetter)
    .sort((a, b) => (b.stmt_date ?? '').localeCompare(a.stmt_date ?? ''));
  const allInPeriod    = retro.filter(r => r.covering_letters > 0);
  const neverMentioned = allInPeriod.filter(r => r.mentioned_in === 0);
  const multiCycle     = allInPeriod.filter(r => r.missed_by >= 2);
  const inScopeTip = 'In-scope: incidents whose Bugzilla filing date falls within the covered audit period.';

  const Field = ({ label, value, color, sub }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: '4px 0', borderBottom: `1px solid ${C.bd}40`, gap: 8 }}>
      <span style={{ fontSize: 11, color: C.t3, flexShrink: 0 }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ fontSize: 12, color: color ?? C.tx, fontWeight: 500 }}>{value}</span>
        {sub && <div style={{ fontSize: 10, color: C.t3 }}>{sub}</div>}
      </div>
    </div>
  );

  const SubHead = ({ children }) => (
    <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, textTransform: 'uppercase',
      letterSpacing: '0.05em', marginBottom: 6, marginTop: 14 }}>{children}</div>
  );

  return (
    <div style={{ paddingTop: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>

        {/* ── Left: Audit facts + quality score ── */}
        <div>
          <SubHead>Audit Details</SubHead>
          <div style={{ marginBottom: 4 }}>
            <Field label="Auditor" value={p.primary_auditor ?? '—'} />
            <Field label="Framework" value={p.primary_framework ?? '—'}
              color={p.primary_framework === 'WebTrust' ? C.ac : C.pu} />
            <Field label="Audit period" value={
              p.latest_period_start && p.latest_period_end
                ? `${p.latest_period_start.slice(0,7)} → ${p.latest_period_end.slice(0,7)}`
                : p.latest_period_end?.slice(0,7) ?? '—'
            } />
            {crit.criteria_version && (
              <Field label="Standard"
                value={`${p.primary_framework === 'ETSI' ? 'ETSI EN 319 411' : 'WebTrust'} v${crit.criteria_version}`}
                color={crit.criteria_current === false ? C.rd : C.t2}
                sub={crit.criteria_current === false ? 'outdated at time of audit' : undefined} />
            )}
            {p.primary_framework === 'ETSI' && crit.aal_version && (
              <Field label="AAL template" value={`V${crit.aal_version}`}
                color={crit.aal_current === false ? C.rd : C.t2}
                sub={crit.aal_current === false ? 'outdated at time of audit' : undefined} />
            )}
            <Field label="Roots covered"
              value={`${rc.roots_with_url ?? 0} of ${rc.total_roots ?? 0}`}
              color={rc.roots_without_url > 0 ? C.am : C.t2}
              sub={rc.roots_without_url > 0 ? `${rc.roots_without_url} without audit URL` : undefined} />
            {trends.letter_count > 1 && (
              <Field label="History"
                value={`${trends.letter_count} letters (${trends.oldest_stmt_date?.slice(0,4)}–${trends.newest_stmt_date?.slice(0,4)})`}
                sub={trends.auditor_changes?.length > 0
                  ? `${trends.auditor_changes.length} auditor change${trends.auditor_changes.length > 1 ? 's' : ''}`
                  : undefined} />
            )}
          </div>

          {qs.dimensions && (
            <>
              <SubHead>Letter Quality Score</SubHead>
              {Object.entries(qs.dimensions).map(([k, v]) => {
                const meta = dimLabels[k] ?? { l: k.replace(/_/g, ' '), tip: '' };
                const g = qualityGrade(v);
                let detail = null;
                if (k === 'disclosure_completeness') {
                  const idc = p.incident_disclosure_check ?? {};
                  const inPeriod = idc.bugs_in_period?.length ?? 0;
                  const mentioned = idc.disclosed_in_letter?.length ?? 0;
                  if (inPeriod === 0) detail = { text: 'No incidents open during this period', na: true };
                  else detail = {
                    text: `${mentioned} of ${inPeriod} cited by BZ number`,
                    note: mentioned === 0 ? 'May be addressed without explicit citation — see incident coverage →' : null,
                  };
                } else if (k === 'template_compliance') {
                  const aal = crit.aal_version;
                  const cur = crit.aal_current;
                  const required = (p.latest_period_end ?? '') >= '2026-03' ? '3.5' : '3.4';
                  if (p.primary_framework !== 'ETSI') detail = { text: 'Not applicable (WebTrust)', na: true };
                  else if (!aal) detail = { text: 'Template version not found' };
                  else if (cur === false) detail = { text: `Used V${aal} — V${required} required` };
                  else detail = { text: `Used V${aal} — correct version` };
                } else if (k === 'criteria_currency') {
                  const ver = crit.criteria_version;
                  const cur = crit.criteria_current;
                  if (cur === false && ver) detail = { text: `v${ver} — outdated at time of audit` };
                  else if (cur === true && ver) detail = { text: `v${ver} — current at time of audit` };
                } else if (k === 'scope_coverage') {
                  const oc = p.oid_check ?? {};
                  if (oc.gaps?.length > 0) detail = { text: `Missing: ${oc.gaps.slice(0,3).join(', ')}` };
                  else if (oc.cert_types?.length > 0) detail = { text: `Covers: ${oc.cert_types.join(', ')}` };
                }
                if (detail?.na) {
                  return (
                    <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8,
                      marginBottom: 5, opacity: 0.45 }}>
                      <div style={{ flex: 1, fontSize: 11, color: C.t2 }} title={meta.tip}>{meta.l}</div>
                      <span style={{ fontSize: 10, color: C.t3 }}>N/A</span>
                    </div>
                  );
                }
                return (
                  <div key={k} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}
                    title={meta.tip}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 11, color: C.tx }}>{meta.l}</div>
                      <div style={{ fontSize: 10, color: C.t3, marginTop: 1 }}>{detail?.text ?? meta.tip}</div>
                      {detail?.note && (
                        <div style={{ fontSize: 10, color: C.t3, marginTop: 2, fontStyle: 'italic' }}>{detail.note}</div>
                      )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: g?.color ?? C.t3, minWidth: 16 }}>
                        {g?.grade ?? '—'}
                      </span>
                      <div style={{ width: 40, height: 4, background: C.s2, borderRadius: 2 }}>
                        {v != null && <div style={{ width: `${v}%`, height: '100%',
                          background: g?.color ?? C.t3, borderRadius: 2 }} />}
                      </div>
                    </div>
                  </div>
                );
              })}
            </>
          )}
        </div>

        {/* ── Right: Incident coverage + what auditor noted ── */}
        <div>
          <SubHead>Incident Coverage by Letter</SubHead>
          {letterRows.length === 0 ? (
            <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.7, marginBottom: 14 }}>
              {tg.incident_count != null
                ? <>{tg.incident_count} Bugzilla incidents on record. Per-letter breakdown populates after next data run.</>
                : 'No incident data available.'}
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
                {letterRows.map((lt, i) => {
                  const total = lt.mentioned.length + lt.notMentioned.length;
                  const pct   = total > 0 ? Math.round(lt.mentioned.length / total * 100) : 0;
                  const col   = pct >= 70 ? C.gn : pct >= 30 ? C.am : C.rd;
                  return (
                    <div key={lt.stmt_date} style={{ padding: '6px 10px', borderRadius: 5,
                      background: i === 0 ? C.s2 : 'transparent',
                      border: `1px solid ${i === 0 ? C.bd : ALPHA.bd31}` }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between',
                        alignItems: 'baseline', marginBottom: 3 }}>
                        <span style={{ fontSize: 10, color: C.t3, fontFamily: FONT_MONO }}>
                          {lt.period_start?.slice(0,7)} → {lt.period_end?.slice(0,7)}
                        </span>
                        <span style={{ fontSize: 11, fontWeight: 600, color: col }}>
                          {lt.mentioned.length}/{total}
                          <span style={{ fontSize: 10, fontWeight: 400, color: C.t3, marginLeft: 4 }}
                            title={inScopeTip}>in-scope</span>
                        </span>
                      </div>
                      <div style={{ height: 3, background: C.s1, borderRadius: 2 }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: col, borderRadius: 2 }} />
                      </div>
                    </div>
                  );
                })}
              </div>
              {allInPeriod.length > 0 && (
                <div style={{ fontSize: 11, color: C.t3, padding: '6px 10px', background: C.s2,
                  borderRadius: 5, marginBottom: 14, lineHeight: 1.5 }}>
                  {neverMentioned.length === 0 ? (
                    <><b style={{ color: C.gn }}>All {allInPeriod.length}</b> in-scope incidents mentioned across covering letters.</>
                  ) : (
                    <><b style={{ color: C.rd }}>{neverMentioned.length} of {allInPeriod.length}</b> in-scope incidents not mentioned in any covering letter.</>
                  )}
                  {multiCycle.length > 0 && (
                    <> <b style={{ color: C.rd }}>{multiCycle.length}</b> persisted across 2+ audit cycles.</>
                  )}
                </div>
              )}
            </>
          )}

          {(p.disclosed_matters?.length > 0) && (
            <>
              <SubHead>What the Auditor Noted ({p.disclosed_matters.length})</SubHead>
              {p.disclosed_matters.map((m, i) => (
                <div key={`matter-${i}-${m.topic || ''}`} style={{ padding: '6px 10px', marginBottom: 4, borderRadius: 4,
                  background: C.s2, fontSize: 11 }}>
                  <div style={{ color: C.tx, marginBottom: 2 }}>
                    {m.topic && <span style={{ fontWeight: 500, marginRight: 6 }}>{m.topic}:</span>}
                    {m.summary ? m.summary.slice(0, 110) : 'No summary available'}
                    {m.summary?.length > 110 && '…'}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2, flexWrap: 'wrap' }}>
                    {m.certificate_count > 0 && (
                      <span style={{ fontSize: 10, color: C.am }}>{m.certificate_count.toLocaleString()} certs affected</span>
                    )}
                    {m.self_reported && <span style={{ fontSize: 10, color: C.t3 }}>self-reported</span>}
                    {(m.bugzilla_ids?.length > 0) && m.bugzilla_ids.map((id, j) => (
                      <a key={j} href={`https://bugzilla.mozilla.org/show_bug.cgi?id=${id}`}
                        target="_blank" rel="noopener noreferrer"
                        style={{ fontSize: 10, color: C.ac, textDecoration: 'none' }}>BZ#{id} ↗</a>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ── Full-width: expandable incident retrospective ── */}
      {(p.bug_retrospective?.length > 0) && (
        <BugRetrospective bugs={p.bug_retrospective} />
      )}
      {(p.bug_retrospective != null && p.bug_retrospective.length === 0 &&
        (p.transparency_gap ?? {}).incident_count > 0) && (
        <div style={{ fontSize: 12, color: C.t3, marginTop: 12, fontStyle: 'italic' }}>
          Retrospective analysis pending — requires audit period dates on historical letters.
        </div>
      )}
    </div>
  );
}

// ── SUMMARY STATS ─────────────────────────────────────────────────────────────
function SummaryStats({ summary, profiles, aggregates }) {
  const parsed = summary?.pdf_parsed_count ?? profiles.filter(p => p.pdf_parsed).length;
  const qual   = summary?.qualified_opinions ?? profiles.filter(p => p.opinion_type === 'qualified').length;

  const retroStats = useMemo(() => {
    let covered = 0, caught = 0, multiCycle = 0;
    profiles.forEach(p => {
      (p.bug_retrospective ?? []).forEach(r => {
        if (r.covering_letters > 0) {
          covered++;
          if (r.mentioned_in > 0) caught++;
          else if (r.missed_by >= 2) multiCycle++;
        }
      });
    });
    return {
      covered, caught, multiCycle,
      detectionRate: covered > 0 ? Math.round(caught / covered * 100) : null,
    };
  }, [profiles]);

  const unauditedRoots = useMemo(() =>
    profiles.reduce((n, p) => n + ((p.root_coverage?.roots_without_url) ?? 0), 0),
  [profiles]);

  const staleCount = (summary?.staleness_buckets?.stale ?? 0) +
                     (summary?.staleness_buckets?.very_stale ?? 0) ||
                     profiles.filter(p => p.staleness === 'stale' || p.staleness === 'very_stale').length;

  const switchImpact = useMemo(() => {
    if (!aggregates) return null;
    const sinceYear = new Date().getFullYear() - 1;
    let scored = 0, improvements = 0, declines = 0;
    profiles.forEach(p => {
      (p.timeline_trends?.auditor_changes ?? []).forEach(c => {
        if ((c.year ?? 0) < sinceYear) return;
        const fromQ = (aggregates[c.from_auditor] ?? {}).avg_quality_score;
        const toQ   = (aggregates[c.to_auditor]   ?? {}).avg_quality_score;
        if (fromQ == null || toQ == null) return;
        const delta = toQ - fromQ;
        scored++;
        if (delta > 5)  improvements++;
        if (delta < -5) declines++;
      });
    });
    if (scored === 0) return null;
    return { scored, improvements, declines };
  }, [profiles, aggregates]);

  // Auditor change spike — peak year vs typical baseline
  const changeSpikeStats = useMemo(() => {
    const byYear = {};
    profiles.forEach(p => {
      (p.timeline_trends?.auditor_changes ?? []).forEach(c => {
        const yr = c.year;
        if (yr) byYear[yr] = (byYear[yr] ?? 0) + 1;
      });
    });
    const entries = Object.entries(byYear).sort((a, b) => a[0] - b[0]);
    if (entries.length < 2) return null;
    const peak = entries.reduce((a, b) => b[1] > a[1] ? b : a);
    const others = entries.filter(([yr]) => yr !== peak[0]);
    const baseline = Math.round(others.reduce((s, [, n]) => s + n, 0) / others.length);
    return { peakYear: peak[0], peakCount: peak[1], baseline };
  }, [profiles]);

  return (
    <div style={{ ...narrowStatGrid, marginBottom: 20 }}>
      <StatCard
        l="Auditor detection rate"
        v={retroStats.detectionRate != null ? `${retroStats.detectionRate}%` : '—'}
        s={retroStats.covered > 0
          ? `${retroStats.caught} of ${retroStats.covered} incidents filed during an open audit period mentioned in the letter — a lower bound; see Methodology for the full CCADB §5 scope`
          : 'populates after retrospective data builds'}
        c={retroStats.detectionRate != null && retroStats.detectionRate < 50 ? C.rd : undefined} />

      <StatCard
        l="Passed through multiple audits undetected"
        v={retroStats.multiCycle > 0 ? retroStats.multiCycle : '—'}
        s="incidents not mentioned in 2+ consecutive annual audit reports"
        c={retroStats.multiCycle > 0 ? C.rd : undefined} />

      <StatCard
        l="Audit report overdue"
        v={profiles.length > 0 ? `${Math.round(staleCount / profiles.length * 100)}%` : '—'}
        s={`${staleCount} of ${profiles.length} CAs — most recent audit report is over 1 year old`}
        c={staleCount > 10 ? C.rd : staleCount > 0 ? C.am : undefined} />

      <StatCard
        l="Auditors flagged exceptions"
        v={parsed > 0 ? `${Math.round(qual / parsed * 100)}%` : '—'}
        s={`${qual} of ${parsed} audit reports — auditor could not fully certify compliance`}
        c={qual > 0 ? C.am : undefined} />

      <StatCard
        l="Root certs without an audit report"
        v={unauditedRoots > 0 ? unauditedRoots : '0'}
        s="trusted root certificates with no traceable audit report URL on file"
        c={unauditedRoots > 0 ? C.am : undefined} />

      {changeSpikeStats && (
        <StatCard
          l="Auditor switches in peak year"
          v={changeSpikeStats.peakCount}
          s={`${changeSpikeStats.peakYear} — vs typical ${changeSpikeStats.baseline}–${changeSpikeStats.baseline + 1} per year`}
          c={changeSpikeStats.peakCount > changeSpikeStats.baseline * 3 ? C.am : undefined} />
      )}

      <StatCard
        l="Letter quality after recent auditor switches"
        v={switchImpact
          ? switchImpact.declines > switchImpact.improvements
            ? `${Math.round(switchImpact.declines / switchImpact.scored * 100)}% lower quality`
            : `${Math.round(switchImpact.improvements / switchImpact.scored * 100)}% higher quality`
          : '—'}
        s={switchImpact
          ? `${switchImpact.declines} switches to lower-scoring firms, ${switchImpact.improvements} to higher-scoring, of ${switchImpact.scored} scored`
          : 'no scored switches yet'}
        c={switchImpact
          ? switchImpact.declines > switchImpact.improvements ? C.rd : C.gn
          : undefined} />
    </div>
  );
}

// ── COMPONENT: Distrust audit retrospective ──────────────────────────────────
function DistrustAuditRetrospective({ data }) {
  const [expanded, setExpanded] = React.useState(null);
  if (!data?.length) return null;

  const withScope = data.filter(r => r.bugs_in_scope > 0);
  const totalScope = withScope.reduce((s, r) => s + r.bugs_in_scope, 0);
  const totalCaught = withScope.reduce((s, r) => s + r.bugs_caught, 0);
  const overallRate = totalScope > 0 ? Math.round(totalCaught / totalScope * 100) : 0;



  // Render the rate cell — or a clearly-labelled reason why it's absent
  function RateCell({ r }) {
    if (r.timeline_status === 'overlap') {
      const pct = r.detection_pct;
      const color = pct === 0 ? C.rd : pct < 30 ? C.am : C.gn;
      return <span style={{ fontWeight: 600, color }}>{pct}%</span>;
    }
    if (r.timeline_status === 'post_date') {
      return (
        <span style={{ color: C.t3, fontSize: 10 }}
          title="CCADB only has audit letters from after the compliance failures occurred. The letters that should have caught these bugs predate current CCADB coverage.">
          letters post-date bugs
        </span>
      );
    }
    // no_record
    return (
      <span style={{ color: C.t3, fontSize: 10 }}
        title="This CA was removed from trust stores before audit records were collected in CCADB. No letters available to analyse.">
        no CCADB record
      </span>
    );
  }

  return (
    <Card>
      <CardTitle sub="For each distrusted CA with available audit history, did the audit letters covering the compliance period mention the bugs that ultimately contributed to distrust? These CAs are excluded from the main detection metrics — this section asks whether audits caught the failures that mattered most.">
        Did auditors catch what led to distrust?
      </CardTitle>

      {withScope.length > 0 && (
        <div style={{ display: 'flex', gap: 24, marginBottom: 16, flexWrap: 'wrap' }}>
          <StatCard label="Detection rate — distrust cases" value={`${overallRate}%`}
            sub={`${totalCaught} of ${totalScope} in-scope bugs mentioned in letter`}
            color={overallRate < 20 ? C.rd : overallRate < 50 ? C.am : C.gn} />
          <StatCard label="CAs with matchable audit periods" value={withScope.length}
            sub={`of ${data.length} distrusted CAs with Bugzilla history`} />
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: `2px solid ${C.bd}` }}>
              {['CA', 'Auditor', 'Year'].map(h => (
                <th key={h} style={{ padding: '6px 8px', textAlign: 'left', fontSize: 11, color: C.t2, fontWeight: 600 }}>{h}</th>
              ))}
              {['Total bugs', 'In-scope', 'Caught', 'Rate'].map(h => (
                <th key={h} style={{ padding: '6px 8px', textAlign: 'right', fontSize: 11, color: C.t2, fontWeight: 600 }}>{h}</th>
              ))}
              <th style={{ padding: '6px 8px', textAlign: 'left', fontSize: 11, color: C.t2, fontWeight: 600 }}>Opinion</th>
            </tr>
          </thead>
          <tbody>
            {data.map(r => {
              const isX = expanded === r.ca;
              const hasRetro = r.retrospective?.filter(b => b.covering_letters > 0).length > 0;
              return (
                <React.Fragment key={r.ca}>
                  <tr style={{ borderBottom: `1px solid ${C.bd}`,
                               cursor: hasRetro ? 'pointer' : 'default',
                               background: isX ? C.s2 : 'transparent' }}
                    onClick={() => hasRetro && setExpanded(isX ? null : r.ca)}>
                    <td style={{ padding: '6px 8px', fontWeight: 500 }}>
                      {hasRetro && <span style={{ fontSize: 10, color: C.t3, marginRight: 4 }}>{isX ? '▼' : '▶'}</span>}
                      {r.ca}
                    </td>
                    <td style={{ padding: '6px 8px', color: C.t2 }}>{r.auditor ?? '—'}</td>
                    <td style={{ padding: '6px 8px', color: C.t2 }}>{r.distrust_year ?? '—'}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{r.total_bugs}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                      {r.bugs_in_scope > 0 ? r.bugs_in_scope : '—'}
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                      {r.bugs_in_scope > 0 ? r.bugs_caught : '—'}
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                      <RateCell r={r} />
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      {r.opinion_type === 'qualified'
                        ? <span style={{ color: C.am, fontWeight: 600 }}>Qualified</span>
                        : r.opinion_type === 'unqualified'
                          ? <span style={{ color: C.gn }}>Clean</span>
                          : <span style={{ color: C.t3 }}>—</span>}
                    </td>
                  </tr>
                  {isX && hasRetro && (
                    <tr>
                      <td colSpan={8} style={{ background: C.s1, padding: '8px 12px' }}>
                        <div style={{ fontSize: 11, color: C.t2, marginBottom: 6 }}>
                          {r.retrospective.filter(b => b.covering_letters > 0).length} bugs covered by at least one audit period:
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          {r.retrospective.filter(b => b.covering_letters > 0).map(b => (
                            <div key={b.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                              <span style={{ color: b.mentioned_in > 0 ? C.gn : C.rd, fontSize: 13, lineHeight: 1.2 }}>
                                {b.mentioned_in > 0 ? '✓' : '✗'}
                              </span>
                              <div>
                                <a href={`https://bugzilla.mozilla.org/show_bug.cgi?id=${b.id}`}
                                   target="_blank" rel="noopener noreferrer"
                                   style={{ color: C.ac, fontSize: 11 }}>Bug {b.id}</a>
                                <span style={{ color: C.t3, fontSize: 11 }}> · {b.filed}</span>
                                <span style={{ color: C.t2, fontSize: 11, marginLeft: 6 }}>{b.summary?.slice(0, 100)}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: C.t3, marginTop: 10, lineHeight: 1.7 }}>
        <b>In-scope:</b> bugs filed while at least one CCADB audit period was open for this CA.<br />
        <b>Letters post-date bugs:</b> CCADB has audit records for this CA, but all periods begin <i>after</i> the compliance failures occurred. The letters that should have caught the bugs predate current CCADB coverage — a data gap, not a clean bill of health.<br />
        <b>No CCADB record:</b> CA was removed from trust stores before audit records were collected in CCADB.
      </div>
    </Card>
  );
}

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function AuditView() {
  const { auditsData } = usePipeline();
  const profiles      = auditsData?.profiles ?? [];
  const aggregates    = auditsData?.auditor_aggregates ?? {};
  const summary       = auditsData?.summary ?? {};
  const insights      = auditsData?.chart_insights ?? {};
  const distrustRetro = auditsData?.distrust_audit_retrospective ?? [];
  const hasPdfData = (summary?.pdf_parsed_count ?? profiles.filter(p => p.pdf_parsed).length) > 0;

  // Compute detection rate for the intro
  if (!profiles.length) {
    return (
      <div style={{ padding: '48px 0', textAlign: 'center', color: C.t3, fontSize: 12 }}>
        Audit data unavailable — run pipeline/fetch_audits.py to generate.
      </div>
    );
  }

  return (
    <div style={{ fontFamily: FONT_SANS }}>
      <TabIntro tabId="audit" quote="Trust, but verify. — Russian proverb">
        Every CA trusted by your browser is required to be audited annually.
        Auditors issue letters certifying that the CA's operations meet industry
        standards — but these letters are written by firms the CA pays, covering
        periods the CA selects, using criteria the CA discloses.
        Meanwhile, Mozilla's public incident database records what actually happened.
        <br /><br />
        The audit system rests on a presumption: that each letter covers the
        specific roots browsers actually trust, and that failures the letter
        doesn't mention are genuinely absent from the CA's record.
        This tab tests both halves of that presumption.
        For each incident that fell inside an active audit period, did the letter
        mention it? And do letters enumerate the root fingerprints that would
        let anyone verify the audit covered the right certificates?
      </TabIntro>

      <SummaryStats summary={summary} profiles={profiles} aggregates={aggregates} />

      {/* ── Section 1 ── */}
      <SectionHead>Patterns visible without reading the audit reports</SectionHead>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 12 }}>
        <AuditorChangesChart profiles={profiles} insight={insights.auditor_changes} />
        <SelfReportChart profiles={profiles} insight={insights.self_report} />
      </div>
      <FrameworkComparisonCard profiles={profiles} />

      {/* ── Section 2 ── */}
      <SectionHead>Do audit letters cover the full scope of what CAs are trusted to issue?</SectionHead>
      {!hasPdfData
        ? <PdfPendingInline />
        : <AuditLetterCompleteness profiles={profiles} summary={summary} />
      }

      {/* ── Section 3 ── */}
      <SectionHead>Did auditors catch what was happening on their watch?</SectionHead>
      {!hasPdfData
        ? <PdfPendingInline />
        : <>
            <AuditorDetectionChart profiles={profiles} insight={insights.detection_rate} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 12 }}>
              <QualityOverTime profiles={profiles} />
              <EtsiAalChart    profiles={profiles} insight={insights.etsi_aal} />
            </div>
            <AuditorScorecard aggregates={aggregates} />
            <TransparencyMatrix profiles={profiles} />
          </>
      }

      {/* ── Section 4 ── */}
      <SectionHead>What browser vendors are exposed to</SectionHead>
      <StorePostureChart profiles={profiles} />

      {/* ── Section 5 ── */}
      <SectionHead>Who audits whom — and at what quality?</SectionHead>
      <AuditorConcentration aggregates={aggregates} summary={summary} />
      <AuditorTimeliness profiles={profiles} />
      <RecentChangesTable profiles={profiles} aggregates={aggregates} />

      {/* ── Section 6 ── */}
      <SectionHead>CA-by-CA Audit Letter Quality</SectionHead>
      <CATable profiles={profiles} />

      {/* ── Section 7 ── */}
      {distrustRetro.length > 0 && (
        <>
          <SectionHead>Did auditors catch what led to distrust?</SectionHead>
          <DistrustAuditRetrospective data={distrustRetro} />
        </>
      )}

      <MethodologyCard title="Methodology">
        <MethodologyItem label="Scope and corpus">
          <b>Different sections use different source corpora. Counts are not intended to reconcile across sections.</b>
          <br /><br />
          Four different incident scopes appear across the tab — each answers a different question:
          <br />• <b>All-time incident count</b> (CA table, self-report rate, transparency gap): every Bugzilla compliance bug ever filed for this CA, regardless of date or audit period.
          <br />• <b>Transparency gap</b>: compares all-time Bugzilla history against the <i>current</i> audit letter only — a coverage signal, not a timing-adjusted one.
          <br />• <b>Bugzilla cross-references in letter</b> (quality score dimension): only bugs filed during the current letter's audit period that were explicitly cited by BZ number.
          <br />• <b>In-period detection rate</b> (retrospective): only bugs <i>filed</i> while any audit period was open, checked against whether that specific period's letter discussed the topic.
          <br /><br />
          <b>Important scope note:</b> CCADB Policy §5 requires audit letters to cover all incidents that "at any time during the audit period, occurred, were open in Bugzilla, or were reported to a Root Store Operator." This means bugs filed <i>before</i> the audit period but still open when the period started must also appear in the letter. Our in-period detection denominator counts only bugs <i>filed during</i> the period — it does not include pre-existing open bugs, because Bugzilla resolution dates are not available in the data. The true policy-mandated denominator is larger, meaning our 30% detection rate likely <i>overstates</i> actual compliance with the disclosure requirement.
          <br /><br />
          Auditor aggregate scores (letter quality comparison chart) are computed across all parsed letters for each firm and do not respond to the Recent/All filter. Incident counts include all Bugzilla filings regardless of whether specific roots were later distrusted.
        </MethodologyItem>

        <MethodologyItem label="Definitions">
          <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #ccc' }}>
                {['Metric', 'Numerator', 'Denominator', 'Exclusions'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                ['In-period detection rate',   'Incidents mentioned in letter',        'Incidents filed during open audit period (see note — CCADB policy requires more)',  'Bugs filed before period that were still open; resolution dates not available'],
                ['Multi-cycle miss',            'Incident not mentioned',               'Incidents covering 2+ audit periods',             'Incidents in only one period'],
                ['Transparency gap score',      'Incidents not Bugzilla-anchored in letter', 'All historical Bugzilla incidents for the CA',  'None — includes timing lag; see per-letter view'],
                ['Letter quality score (0–100)','Weighted dimension scores',            'Applicable dimensions for the audit era',         'Dimensions not applicable to era or framework'],
                ['Staleness',                   '—',                                   'Days since period-end of current audit letter',   'CAs with no audit record'],
                ['Auditor switch direction',    'Score delta (new − prior firm)',       'Switches with both firms having ≥2 parsed letters','Switches to firms with no parsed letters'],
                ['Qualified opinion',           '—',                                   'Parsed audit letters',                            'Unparsed letters; unqualified = clean'],
              ].map(([metric, num, denom, excl]) => (
                <tr key={metric} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: '4px 8px', fontWeight: 500 }}>{metric}</td>
                  <td style={{ padding: '4px 8px', color: '#555' }}>{num}</td>
                  <td style={{ padding: '4px 8px', color: '#555' }}>{denom}</td>
                  <td style={{ padding: '4px 8px', color: '#888', fontStyle: 'italic' }}>{excl}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </MethodologyItem>

        <MethodologyItem label="Letter quality score dimensions">
          Scored 0–100 against the standard current at time of the audit period (not today's).
          Grade thresholds: A ≥90, B ≥75, C ≥60, D ≥40, F &lt;40.
          Dimensions and weights: opinion clarity (1.5×), criteria currency (2×),
          AAL template compliance (2×, ETSI aal_v3x/post_v35 era only),
          disclosure completeness (3×, post-2023 letters only), scope coverage (1.5×).
          Eras: pre_aal (before July 2020), aal_v3x (July 2020–March 2026), post_v35 (March 2026+).
        </MethodologyItem>

        <MethodologyItem label="Transparency gap vs. in-period detection">
          These are two different signals. The <b>transparency gap score</b> compares the CA's entire
          Bugzilla history against the current letter — a coverage signal, not a claim that each
          unmentioned incident should have been individually disclosed. The <b>in-period detection rate</b>
          is narrower: it only counts incidents filed while an audit period was open, so timing lag
          is excluded. Both signals appear together in the per-letter breakdown in each CA's expanded row.
        </MethodologyItem>

        <MethodologyItem label="Auditor switch direction">
          A switch is not itself a quality event. Direction is inferred from the observed historical
          scoring of the incoming firm across its other current clients — not intent, not causal.
          Threshold: &gt;5 pts difference = directional, otherwise neutral.
          Only computed when both firms have ≥2 parsed letters. Confidence: high (≥5), moderate (2–4), low (1).
        </MethodologyItem>

        <MethodologyItem label="European audit report template (AAL)">
          AAL = Audit Attestation Letter, the standardized ETSI report format for European CAs.
          V3.4 was current until March 2026; V3.5 is now mandatory.
        </MethodologyItem>

        <MethodologyItem label="Self-report rate">
          Percentage of a CA's Bugzilla incidents where the CA was the first to report the issue.
          Higher is not necessarily better — it may reflect a culture of disclosure rather than
          fewer problems. Rates differ between WebTrust and ETSI frameworks.
        </MethodologyItem>
      </MethodologyCard>
    </div>
  );
}
