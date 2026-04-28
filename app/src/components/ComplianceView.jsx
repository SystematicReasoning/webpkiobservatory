import React, { useMemo } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from 'recharts';
import { usePipeline } from '../PipelineContext';
import ComplianceVelocity from './ComplianceVelocity';
import { statGridStyle } from '../styles';
import { Card, CardTitle, DataPending, StatCard, MethodologyCard, MethodologyItem } from './shared';

const C = {
  bg: 'var(--bg)', tx: 'var(--tx)', t2: 'var(--t2)', t3: 'var(--t3)',
  bd: 'var(--bd)', ac: 'var(--ac)',
};

// ── Source card — colored header + line items + total ─────────────────────────
const SourceCard = ({ color, title, items, note }) => {
  const total = items.reduce((s, [, v]) => s + (v || 0), 0);
  return (
    <div style={{ border: `1px solid ${color}`, borderRadius: 4, overflow: 'hidden', fontSize: 10 }}>
      <div style={{ background: color, padding: '5px 10px' }}>
        <span style={{ fontWeight: 700, color: '#fff', fontSize: 10, letterSpacing: '0.06em' }}>{title}</span>
      </div>
      <div style={{ padding: '8px 10px', background: C.bg }}>
        {items.map(([label, val]) => (val > 0) && (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
            <span style={{ color: C.t2 }}>{label}</span>
            <span style={{ fontFamily: 'monospace', fontWeight: 600, color: C.tx }}>{(val || 0).toLocaleString()}</span>
          </div>
        ))}
        <div style={{ borderTop: `1px solid ${color}`, marginTop: 4, paddingTop: 5, display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 700, color, fontSize: 10 }}>TOTAL</span>
          <span style={{ fontFamily: 'monospace', fontWeight: 700, color, fontSize: 11 }}>{total.toLocaleString()}</span>
        </div>
        {note && <div style={{ fontSize: 8, color: C.t3, marginTop: 5, lineHeight: 1.4 }}>{note}</div>}
      </div>
    <MethodologyCard>
        <MethodologyItem label="Usage period">365 / (all-time certs / unexpired certs). Measures how frequently a CA's subscribers actually replace certificates, not the validity period configured on the certificate. A CA issuing 90-day certs whose subscribers renew at 60 days has a ~22-day usage period.</MethodologyItem>
        <MethodologyItem label="Active TLS filter">This tab only shows CAs that are active TLS issuers: tls_capable=true, at least 1,000 unexpired certificates, and trusted by at least one current browser store. CAs excluded by this filter have legacy cert populations — old S/MIME certificates, historical code signing chains, or cross-signs that expired years ago but still appear in all-time CT counts — that make their usage period meaningless as a BR compliance signal.</MethodologyItem>
        <MethodologyItem label="Subscriber readiness — >200d">A CA in this tier has a population-average certificate usage period exceeding 200 days. The correct interpretation is subscriber readiness risk, not active compliance violation. Certificates issued before March 15, 2026 are grandfathered.</MethodologyItem>
        <MethodologyItem label="BR schedule">CA/B Forum Baseline Requirements are reducing maximum certificate validity: 200 days (March 15 2026), 100 days (March 15 2027), 47 days (March 15 2029).</MethodologyItem>
        <MethodologyItem label="Limitation">Usage period is a population average. It does not capture subscriber heterogeneity — a CA may have some subscribers with 30-day automation and others doing manual annual renewal.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — parsers">Four convention-aware parsers: RFC2119_INLINE (MUST/SHALL/SHOULD/MAY uppercase), SHALL_LETTERED_LIST (lettered sub-items under SHALL: headers), EU_LEGAL (lowercase 'shall' binding obligations, 'should' excluded as recital guidance), NIST_OSCAL (structured JSON control catalog).</MethodologyItem>
        <MethodologyItem label="Regulatory surface — RFC approach">Operative versions only — RFC 5280 superseded 3280/2459; RFC 9162 superseded 6962; RFC 8659 superseded 6844. NIST uses the High baseline resolved profile (370 controls). 190 ballot entries from document revision history tables.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — caveats">Keyword counts include some definitional uses — trends more reliable than absolute values. ETSI, WebTrust, Chrome, Apple are curated estimates. The 2020 NIST step reflects when NIST was added to measurement scope, not when CAs started facing these obligations.</MethodologyItem>
      </MethodologyCard>
    </div>
  );
};

// ── Grand total — dark box, matches SVG reference ─────────────────────────────
const GrandTotal = ({ total, growth, t2012, mandPct, rows, latest }) => {
  const rowTotals = rows.map(r => ({
    ...r,
    val: r.keys.reduce((s, k) => {
      const v = latest?.by_source?.[k] || {};
      return s + (v.mandatory || 0) + (v.recommended || 0) + (v.optional || 0);
    }, 0),
  }));
  return (
    <div style={{ background: '#1a252f', borderRadius: 4, padding: '14px 16px' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: '#a8b5c2', letterSpacing: '0.08em', marginBottom: 2 }}>
        GRAND TOTAL
      </div>
      <div style={{ fontSize: 42, fontWeight: 800, color: '#fff', fontFamily: 'monospace', letterSpacing: '-0.03em', lineHeight: 1 }}>
        {total.toLocaleString()}
      </div>
      <div style={{ fontSize: 9, color: '#a8b5c2', marginTop: 3 }}>normative obligations (2026)</div>
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.15)', margin: '8px 0 6px', fontSize: 9, color: '#7f8c9b', paddingTop: 6 }}>
        vs. {t2012.toLocaleString()} in 2012 ({growth}× growth) · {mandPct}% mandatory
      </div>
      {rowTotals.map(r => (
        <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, fontSize: 9 }}>
          <span style={{ color: '#7f8c9b' }}>{r.label}</span>
          <span style={{ fontFamily: 'monospace', fontWeight: 600, color: r.color }}>{r.val.toLocaleString()}</span>
        </div>
      ))}
    <MethodologyCard>
        <MethodologyItem label="Usage period">365 / (all-time certs / unexpired certs). Measures how frequently a CA's subscribers actually replace certificates, not the validity period configured on the certificate. A CA issuing 90-day certs whose subscribers renew at 60 days has a ~22-day usage period.</MethodologyItem>
        <MethodologyItem label="Active TLS filter">This tab only shows CAs that are active TLS issuers: tls_capable=true, at least 1,000 unexpired certificates, and trusted by at least one current browser store. CAs excluded by this filter have legacy cert populations — old S/MIME certificates, historical code signing chains, or cross-signs that expired years ago but still appear in all-time CT counts — that make their usage period meaningless as a BR compliance signal.</MethodologyItem>
        <MethodologyItem label="Subscriber readiness — >200d">A CA in this tier has a population-average certificate usage period exceeding 200 days. The correct interpretation is subscriber readiness risk, not active compliance violation. Certificates issued before March 15, 2026 are grandfathered.</MethodologyItem>
        <MethodologyItem label="BR schedule">CA/B Forum Baseline Requirements are reducing maximum certificate validity: 200 days (March 15 2026), 100 days (March 15 2027), 47 days (March 15 2029).</MethodologyItem>
        <MethodologyItem label="Limitation">Usage period is a population average. It does not capture subscriber heterogeneity — a CA may have some subscribers with 30-day automation and others doing manual annual renewal.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — parsers">Four convention-aware parsers: RFC2119_INLINE (MUST/SHALL/SHOULD/MAY uppercase), SHALL_LETTERED_LIST (lettered sub-items under SHALL: headers), EU_LEGAL (lowercase 'shall' binding obligations, 'should' excluded as recital guidance), NIST_OSCAL (structured JSON control catalog).</MethodologyItem>
        <MethodologyItem label="Regulatory surface — RFC approach">Operative versions only — RFC 5280 superseded 3280/2459; RFC 9162 superseded 6962; RFC 8659 superseded 6844. NIST uses the High baseline resolved profile (370 controls). 190 ballot entries from document revision history tables.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — caveats">Keyword counts include some definitional uses — trends more reliable than absolute values. ETSI, WebTrust, Chrome, Apple are curated estimates. The 2020 NIST step reflects when NIST was added to measurement scope, not when CAs started facing these obligations.</MethodologyItem>
      </MethodologyCard>
    </div>
  );
};

// ── Color groups ──────────────────────────────────────────────────────────────
const GC = {
  cabf_op:    '#1a9641',
  cabf_prof:  '#78c679',
  root_prog:  '#e6550d',
  ietf:       '#756bb1',
  audit:      '#d95f02',
  regulatory: '#b22222',
};

const STACK = [
  { key: 'tls_br',        group: 'cabf_op'    },  // PDF-era 2012-2020 (before op/prof split)
  { key: 'tls_br_op',     group: 'cabf_op'    },
  { key: 'ev_g_op',       group: 'cabf_op'    },
  { key: 'ns_reqs',       group: 'cabf_op'    },
  { key: 'ns_reqs_op',    group: 'cabf_op'    },
  { key: 'smime_br_op',   group: 'cabf_op'    },
  { key: 'cs_br_op',      group: 'cabf_op'    },
  { key: 'tls_br_prof',   group: 'cabf_prof'  },
  { key: 'smime_br_prof', group: 'cabf_prof'  },
  { key: 'cs_br_prof',    group: 'cabf_prof'  },
  { key: 'ev_g_prof',     group: 'cabf_prof'  },
  { key: 'mozilla_mrsp',  group: 'root_prog'  },
  { key: 'chrome_root',   group: 'root_prog'  },
  { key: 'apple_root',    group: 'root_prog'  },
  { key: 'rfc_pkix',      group: 'ietf'       },
  { key: 'rfc_ct',        group: 'ietf'       },
  { key: 'rfc_acme',      group: 'ietf'       },
  { key: 'rfc_caa',       group: 'ietf'       },
  { key: 'webtrust',      group: 'audit'      },
  { key: 'etsi_stack',    group: 'audit'      },
  { key: 'nist',          group: 'regulatory' },
  { key: 'nis2',          group: 'regulatory' },
];

const LEGEND = [
  { label: 'CA/Browser Forum (Operational)',  color: GC.cabf_op,    note: 'validation, audit, key mgmt, CPS' },
  { label: 'CA/Browser Forum (Profile Spec)', color: GC.cabf_prof,  note: 'certificate/CRL field constraints' },
  { label: 'Root Programs',     color: GC.root_prog,  note: 'Mozilla, Chrome, Apple' },
  { label: 'IETF RFCs',         color: GC.ietf,       note: 'operative versions only' },
  { label: 'Audit Frameworks',  color: GC.audit,      note: 'WebTrust, ETSI (curated)' },
  { label: 'Regulatory',        color: GC.regulatory, note: 'NIST High baseline, NIS2' },
];

const MILESTONES = [
  { year: 2004, label: 'Mozilla MRSP',       row: 0, group: 'root_prog'  },
  { year: 2008, label: 'RFC 5280',           row: 1, group: 'ietf'       },
  { year: 2012, label: 'TLS BR v1.0',        row: 0, group: 'cabf_op'   },
  { year: 2016, label: 'CT + CAA RFCs',      row: 1, group: 'ietf'      },
  { year: 2020, label: 'NIST 800-53 Rev 5',  row: 0, group: 'regulatory'},
  { year: 2022, label: 'Chrome independent', row: 1, group: 'root_prog' },
  { year: 2024, label: 'NIS2 enforcement',   row: 0, group: 'regulatory'},
  { year: 2026, label: '47-day certs',        row: 1, group: 'cabf_op'   },
];

// Helper: sum sources
const sumSrc = (latest, keys) =>
  keys.reduce((s, k) => {
    const v = latest?.by_source?.[k] || {};
    return s + (v.mandatory || 0) + (v.recommended || 0) + (v.optional || 0);
  }, 0);

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + (p.value || 0), 0);
  const byGroup = {};
  payload.forEach(p => {
    const src = STACK.find(g => g.key === p.dataKey);
    if (!src || !p.value) return;
    byGroup[src.group] = (byGroup[src.group] || 0) + p.value;
  });
  return (
    <div style={{ background: C.bg, border: `1px solid ${C.bd}`, borderRadius: 6, padding: '8px 12px', fontSize: 10, minWidth: 180 }}>
      <div style={{ fontWeight: 700, marginBottom: 5, color: C.tx, borderBottom: `1px solid ${C.bd}`, paddingBottom: 3 }}>
        {label} — {total.toLocaleString()} total
      </div>
      {LEGEND.map(({ label: lbl, color, group }) => {
        const val = byGroup[Object.keys(GC).find(k => GC[k] === color)] || 0;
        // match group key
        const grpKey = STACK.find(s => GC[s.group] === color)?.group;
        const v = byGroup[grpKey] || 0;
        if (!v) return null;
        return (
          <div key={lbl} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 2 }}>
            <span style={{ color, fontWeight: 500 }}>{lbl}</span>
            <span style={{ fontFamily: 'monospace', color: C.t2 }}>{v.toLocaleString()}</span>
          </div>
        );
      })}
    <MethodologyCard>
        <MethodologyItem label="Usage period">365 / (all-time certs / unexpired certs). Measures how frequently a CA's subscribers actually replace certificates, not the validity period configured on the certificate. A CA issuing 90-day certs whose subscribers renew at 60 days has a ~22-day usage period.</MethodologyItem>
        <MethodologyItem label="Active TLS filter">This tab only shows CAs that are active TLS issuers: tls_capable=true, at least 1,000 unexpired certificates, and trusted by at least one current browser store. CAs excluded by this filter have legacy cert populations — old S/MIME certificates, historical code signing chains, or cross-signs that expired years ago but still appear in all-time CT counts — that make their usage period meaningless as a BR compliance signal.</MethodologyItem>
        <MethodologyItem label="Subscriber readiness — >200d">A CA in this tier has a population-average certificate usage period exceeding 200 days. The correct interpretation is subscriber readiness risk, not active compliance violation. Certificates issued before March 15, 2026 are grandfathered.</MethodologyItem>
        <MethodologyItem label="BR schedule">CA/B Forum Baseline Requirements are reducing maximum certificate validity: 200 days (March 15 2026), 100 days (March 15 2027), 47 days (March 15 2029).</MethodologyItem>
        <MethodologyItem label="Limitation">Usage period is a population average. It does not capture subscriber heterogeneity — a CA may have some subscribers with 30-day automation and others doing manual annual renewal.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — parsers">Four convention-aware parsers: RFC2119_INLINE (MUST/SHALL/SHOULD/MAY uppercase), SHALL_LETTERED_LIST (lettered sub-items under SHALL: headers), EU_LEGAL (lowercase 'shall' binding obligations, 'should' excluded as recital guidance), NIST_OSCAL (structured JSON control catalog).</MethodologyItem>
        <MethodologyItem label="Regulatory surface — RFC approach">Operative versions only — RFC 5280 superseded 3280/2459; RFC 9162 superseded 6962; RFC 8659 superseded 6844. NIST uses the High baseline resolved profile (370 controls). 190 ballot entries from document revision history tables.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — caveats">Keyword counts include some definitional uses — trends more reliable than absolute values. ETSI, WebTrust, Chrome, Apple are curated estimates. The 2020 NIST step reflects when NIST was added to measurement scope, not when CAs started facing these obligations.</MethodologyItem>
      </MethodologyCard>
    </div>
  );
};

export default function ComplianceView() {
  const { complianceData } = usePipeline();

  if (!complianceData) {
    return <DataPending tab="Complexity Growth" source="compliance_growth.json"
      description="Run: python pipeline/fetch_compliance_growth.py && python pipeline/fetch_revision_history.py" />;
  }

  const ts = complianceData.time_series || [];
  const latest = ts[ts.length - 1];
  const y2012  = ts.find(r => r.year === 2012);

  const t2026   = latest?.totals?.total || 0;
  const t2012   = y2012?.totals?.total  || 1;
  const m2026   = latest?.totals?.mandatory || 0;
  const mandPct = t2026 ? Math.round(m2026 / t2026 * 100) : 0;
  const growthX = Math.round(t2026 / t2012);

  const totalBallots = Object.values(complianceData.revision_history || {})
    .reduce((s, v) => s + (Array.isArray(v) ? v.length : 0), 0);

  const activeSources = STACK.filter(g =>
    ts.some(row => {
      const v = row.by_source?.[g.key];
      return v && v.mandatory + v.recommended + v.optional > 0;
    })
  );

  const chartData = useMemo(() => ts.map(row => {
    const d = { year: row.year };
    const hasSplit = (row.by_source?.tls_br_op?.mandatory || 0) +
                     (row.by_source?.tls_br_op?.recommended || 0) +
                     (row.by_source?.tls_br_op?.optional || 0) > 0;
    for (const { key } of STACK) {
      // tls_br (legacy unsplit) only used when tls_br_op/prof don't exist yet
      if (key === 'tls_br' && hasSplit) { d[key] = 0; continue; }
      const v = row.by_source?.[key];
      d[key] = v ? v.mandatory + v.recommended + v.optional : 0;
    }
    return d;
  }), [ts]);

  const distrib = useMemo(() => {
    if (!latest) return { mandatory: 0, recommended: 0, optional: 0, total: 1 };
    let m = 0, r = 0, o = 0;
    Object.values(latest.by_source || {}).forEach(v => {
      m += v.mandatory || 0; r += v.recommended || 0; o += v.optional || 0;
    });
    return { mandatory: m, recommended: r, optional: o, total: m + r + o };
  }, [latest]);

  const GRAND_ROWS = [
    { label: 'CA/Browser Forum', color: GC.cabf_op,    keys: ['tls_br_op','tls_br_prof','ev_g_op','ev_g_prof','ns_reqs','ns_reqs_op','smime_br_op','smime_br_prof','cs_br_op','cs_br_prof'] },
    { label: 'Root Programs', color: GC.root_prog,  keys: ['mozilla_mrsp','chrome_root','apple_root'] },
    { label: 'Audit + IETF',  color: GC.audit,      keys: ['webtrust','etsi_stack','rfc_pkix','rfc_ct','rfc_caa','rfc_acme'] },
    { label: 'Regulatory',    color: GC.regulatory, keys: ['nist','nis2'] },
  ];

  return (
    <div>
      {/* ── KPI row ── */}
      <div style={statGridStyle}>
        <StatCard l="Total Obligations (2026)" v={t2026.toLocaleString()}
          s="across all computed + curated sources" c="var(--rd)" />
        <StatCard l="Growth Since 2000"
          v={(() => {
            const first = ts.find(r => r.totals?.total > 0);
            return first && first.totals.total > 0
              ? `${Math.round(t2026 / first.totals.total)}×`
              : `${growthX}×`;
          })()}
          s={(() => {
            const first = ts.find(r => r.totals?.total > 0);
            return first ? `${first.totals.total.toLocaleString()} obligations in ${first.year}` : '';
          })()}
          c="var(--am)" />
        <StatCard l="Mandatory (MUST/SHALL)"
          v={`${mandPct}%`}
          s={`${m2026.toLocaleString()} of ${t2026.toLocaleString()} total`} c="var(--rd)" />
        <StatCard l="CA/Browser Forum Ballots"
          v={totalBallots || '190+'}
          s="from document revision history tables" c="var(--gn)" />
      </div>

      {/* ── Stacked area chart ── */}
      <Card>
        <CardTitle sub="Cumulative normative obligation language by source group, 2000–2026. CA/Browser Forum split: operational obligations vs certificate profile specifications.">
          Compliance Obligation Growth
        </CardTitle>

        <ResponsiveContainer width="100%" height={340}>
          <AreaChart data={chartData} margin={{ left: 8, right: 8, top: 8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.bd} strokeOpacity={0.5} />
            <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']}
              tick={{ fontSize: 9, fill: C.t3 }} tickCount={14} />
            <YAxis tick={{ fontSize: 9, fill: C.t3 }} width={28}
              tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
            <Tooltip content={<CustomTooltip />} />
            {MILESTONES.map(m => (
              <ReferenceLine key={`${m.year}-${m.row}`} x={m.year}
                stroke={GC[m.group]} strokeDasharray="4 3" strokeOpacity={0.5} />
            ))}
            {activeSources.map(({ key, group }) => (
              <Area key={key} type="monotone" dataKey={key} name={key}
                stackId="1" fill={GC[group]} stroke={GC[group]}
                fillOpacity={0.85} strokeWidth={0} />
            ))}
          </AreaChart>
        </ResponsiveContainer>

        {/* Milestone callout rows */}
        <div className="milestone-labels">
        {[0, 1].map(row => (
          <div key={row} style={{ position: 'relative', height: 28, marginTop: row === 0 ? 4 : 0, overflow: 'visible' }}>
            {MILESTONES.filter(m => m.row === row).map(m => {
              // Map year to % of chart width (2000–2026, accounting for recharts left margin of ~8px)
              const rawPct = ((m.year - 2000) / 26) * 100;
              // For labels near the right edge, anchor right instead of centering
              const nearRight = rawPct > 85;
              const nearLeft  = rawPct < 10;
              const leftVal   = `calc(${rawPct}% + 4px)`;
              return (
                <div key={m.year} style={{
                  position: 'absolute',
                  left:      nearRight ? 'auto' : leftVal,
                  right:     nearRight ? '0px'  : 'auto',
                  transform: nearRight ? 'none' : nearLeft ? 'none' : 'translateX(-50%)',
                  background: C.bg,
                  border: `1px solid ${GC[m.group]}`, borderRadius: 3,
                  padding: '1px 5px', fontSize: 8, color: C.t2,
                  whiteSpace: 'nowrap', fontWeight: 500,
                }}>
                  <span style={{ color: GC[m.group], fontWeight: 700 }}>{m.year}</span>
                  {' · '}{m.label}
                </div>
              );
            })}
          </div>
        ))}
        </div>

        {/* Legend grid */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
          gap: '6px 12px', marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.bd}`,
        }}>
          {LEGEND.map(g => (
            <div key={g.label} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
              <span style={{ width: 12, height: 12, background: g.color, borderRadius: 2,
                display: 'inline-block', flexShrink: 0, marginTop: 1 }} />
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: C.tx, lineHeight: 1.2 }}>{g.label}</div>
                <div style={{ fontSize: 9, color: C.t3, marginTop: 1 }}>{g.note}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 8, color: C.t3, marginTop: 6, lineHeight: 1.5 }}>
          Audit frameworks (WebTrust, ETSI) and root programs are curated estimates.
          All CA/Browser Forum documents and RFCs computed from primary source text.
          NIST uses the High baseline (370 controls).
        </div>
      </Card>

      {/* ── Ballot velocity ── */}
      <ComplianceVelocity complianceData={complianceData} />

      {/* ── RFC 2119 distribution bar ── */}
      <Card>
        <CardTitle sub="Distribution of obligation language across all sources (2026). Mandatory = MUST/SHALL/shall. Optional = MAY.">
          Obligation Level Distribution
        </CardTitle>
        <div style={{ display: 'flex', height: 22, borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ flex: distrib.mandatory, background: '#c0392b' }} />
          <div style={{ flex: distrib.recommended, background: '#e67e22', marginLeft: 2 }} />
          <div style={{ flex: distrib.optional, background: '#3498db', marginLeft: 2 }} />
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', marginTop: 7, fontSize: 9 }}>
          {[
            { label: 'Mandatory (MUST/SHALL)', color: '#c0392b', v: distrib.mandatory },
            { label: 'Recommended (SHOULD)',   color: '#e67e22', v: distrib.recommended },
            { label: 'Optional (MAY)',          color: '#3498db', v: distrib.optional },
          ].map(({ label, color, v }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 10, height: 10, background: color, borderRadius: 2, display: 'inline-block' }} />
              <span style={{ color: C.t2 }}>{label}</span>
              <span style={{ color: C.tx, fontWeight: 600, fontFamily: 'monospace' }}>
                {v.toLocaleString()} ({Math.round(v / distrib.total * 100)}%)
              </span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 8, color: C.t3, marginTop: 5 }}>
          NIST 800-53 controls counted as mandatory. NIS2 EU 'should' excluded — recital guidance.
        </div>
      </Card>


    <MethodologyCard>
        <MethodologyItem label="Usage period">365 / (all-time certs / unexpired certs). Measures how frequently a CA's subscribers actually replace certificates, not the validity period configured on the certificate. A CA issuing 90-day certs whose subscribers renew at 60 days has a ~22-day usage period.</MethodologyItem>
        <MethodologyItem label="Active TLS filter">This tab only shows CAs that are active TLS issuers: tls_capable=true, at least 1,000 unexpired certificates, and trusted by at least one current browser store. CAs excluded by this filter have legacy cert populations — old S/MIME certificates, historical code signing chains, or cross-signs that expired years ago but still appear in all-time CT counts — that make their usage period meaningless as a BR compliance signal.</MethodologyItem>
        <MethodologyItem label="Subscriber readiness — >200d">A CA in this tier has a population-average certificate usage period exceeding 200 days. The correct interpretation is subscriber readiness risk, not active compliance violation. Certificates issued before March 15, 2026 are grandfathered.</MethodologyItem>
        <MethodologyItem label="BR schedule">CA/B Forum Baseline Requirements are reducing maximum certificate validity: 200 days (March 15 2026), 100 days (March 15 2027), 47 days (March 15 2029).</MethodologyItem>
        <MethodologyItem label="Limitation">Usage period is a population average. It does not capture subscriber heterogeneity — a CA may have some subscribers with 30-day automation and others doing manual annual renewal.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — parsers">Four convention-aware parsers: RFC2119_INLINE (MUST/SHALL/SHOULD/MAY uppercase), SHALL_LETTERED_LIST (lettered sub-items under SHALL: headers), EU_LEGAL (lowercase 'shall' binding obligations, 'should' excluded as recital guidance), NIST_OSCAL (structured JSON control catalog).</MethodologyItem>
        <MethodologyItem label="Regulatory surface — RFC approach">Operative versions only — RFC 5280 superseded 3280/2459; RFC 9162 superseded 6962; RFC 8659 superseded 6844. NIST uses the High baseline resolved profile (370 controls). 190 ballot entries from document revision history tables.</MethodologyItem>
        <MethodologyItem label="Regulatory surface — caveats">Keyword counts include some definitional uses — trends more reliable than absolute values. ETSI, WebTrust, Chrome, Apple are curated estimates. The 2020 NIST step reflects when NIST was added to measurement scope, not when CAs started facing these obligations.</MethodologyItem>
      </MethodologyCard>
    </div>
  );
}
