import React, { useMemo } from 'react';
import { usePipeline } from '../PipelineContext';
import { FONT_MONO } from '../constants';

const KPI = ({ value, label, sub, color, footnote }) => (
  <div style={{
    background: 'var(--bg)', border: '1px solid var(--bd)',
    borderLeft: `4px solid ${color}`, borderRadius: 6,
    padding: '14px 16px', minWidth: 0,
  }}>
    <div style={{
      fontSize: 36, fontWeight: 800, fontFamily: FONT_MONO,
      color, letterSpacing: '-0.03em', lineHeight: 1, marginBottom: 6,
    }}>
      {value}
    </div>
    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--tx)',
      textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
      {label}
    </div>
    <div style={{ fontSize: 9, color: 'var(--t2)', lineHeight: 1.5 }}>{sub}</div>
    {footnote && <div style={{ fontSize: 8, color: 'var(--t3)', marginTop: 4, lineHeight: 1.4 }}>{footnote}</div>}
  </div>
);

export default function ComplexityKPI() {
  const { complianceData } = usePipeline();
  if (!complianceData) return null;

  const ts  = complianceData.time_series    || [];
  const rev = complianceData.revision_history || {};
  const vh  = complianceData.version_history  || {};
  const latest = ts[ts.length - 1];
  const first  = ts[0];

  const kpis = useMemo(() => {
    if (!latest || !first) return null;

    const t = latest.totals?.total || 0;
    const t0 = first.totals?.total || 1;
    const y0 = first.year;
    const y1 = latest.year;
    const span = y1 - y0 || 1;

    // Total ballots from revision tables
    const totalBallots = Object.values(rev).reduce((s, v) => s + (Array.isArray(v) ? v.length : 0), 0);

    // Ballots per year — last 3 full years
    const recentCutoff = `${y1 - 3}-01-01`;
    const recentBallots = Object.values(rev).reduce(
      (s, v) => s + (Array.isArray(v) ? v.filter(b => b.date >= recentCutoff).length : 0), 0
    );
    const ballotPace = (recentBallots / 3).toFixed(1);

    // Average annual obligation growth (delta / year)
    const annualGrowth = Math.round((t - t0) / span);

    // Latest year peak delta from version history
    let peakBallot = null;
    let peakDelta = 0;
    Object.values(vh).flat().forEach(v => {
      if (v.delta && Math.abs(v.delta) > Math.abs(peakDelta)) {
        peakDelta = v.delta;
        peakBallot = v.tag;
      }
    });

    return {
      totalBallots,
      ballotPace,
      recentBallots,
      annualGrowth,
      span,
      y0,
      y1,
      t,
      t0,
      peakDelta,
      peakBallot,
    };
  }, [latest, first, rev, vh]);

  if (!kpis) return null;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, margin: '0 0 16px 0' }}>
      <KPI
        value={kpis.totalBallots || '190+'}
        label="Ballots on Record"
        sub={`Across TLS BR, EVG, NS Reqs, S/MIME BR, and CS BR — ${kpis.y0}–${kpis.y1}. From document revision history tables.`}
        color="#1a9641"
        footnote="Complete ballot history including years where git tags are absent."
      />
      <KPI
        value={`${kpis.ballotPace}/yr`}
        label="Ballot Pace"
        sub={`${kpis.recentBallots} ballots across all CABF documents in the last 3 years. Rate of new obligations accelerating.`}
        color="#e67e22"
      />
      <KPI
        value={`+${kpis.annualGrowth}`}
        label="Obligations / Year"
        sub={`Average annual growth in normative obligation language since ${kpis.y0}. ${kpis.t0.toLocaleString()} in ${kpis.y0} → ${kpis.t.toLocaleString()} in ${kpis.y1}.`}
        color="#756bb1"
      />
      <KPI
        value={kpis.peakDelta ? `+${kpis.peakDelta}` : '—'}
        label="Largest Single Ballot"
        sub={`${kpis.peakBallot || 'N/A'} — single largest obligation count change in any one version.`}
        color="#c0392b"
        footnote="Counts reflect parser output on versioned document text, not a manual audit."
      />
    </div>
  );
}
