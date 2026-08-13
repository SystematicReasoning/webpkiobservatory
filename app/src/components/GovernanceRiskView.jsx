/**
 * GovernanceRiskView — Tab 12: Governance Risk
 *
 * Compares how effectively Chrome, Mozilla, Apple, and Microsoft govern the
 * CAs they trust — enforcement, oversight, policy leadership, and trust surface.
 *
 * Data source: data/root_program_effectiveness.json (from fetch_rpe.py)
 */
import React, { useState, useMemo } from 'react';
import { COLORS, STORE_COLORS, FONT_MONO, FONT_SANS, GOVERNANCE_MILESTONES } from '../constants';
import {
  Card, CardTitle, DataPending, StatCard, TabIntro, MethodologyCard, MethodologyItem,
} from './shared';
import { usePipeline } from '../PipelineContext';
import { footnoteStyle, statGridStyle } from '../styles';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, Legend,
} from 'recharts';

/* ── Local constants ── */

const STORE_NAMES = { chrome: 'Chrome', mozilla: 'Mozilla', apple: 'Apple', microsoft: 'Microsoft' };
const STORE_ORDER = ['chrome', 'mozilla', 'apple', 'microsoft'];

const Dot = ({ store, size = 8 }) => (
  <span style={{ display: 'inline-block', width: size, height: size, borderRadius: '50%', background: STORE_COLORS[store], verticalAlign: 'middle' }} />
);

/* ── Metric definitions (color thresholds — config, not data) ── */
// recent thresholds are lower since the window is shorter (5 events, 12 quarters, 50 ballots)
const METRICS = [
  { key: 'enforcement', label: 'Enforcement', tip: 'total actions to protect users', good: 'high',
    color: (v, tot) => v === `${tot}/${tot}` ? COLORS.gn : parseInt(v) >= tot - 1 ? COLORS.am : COLORS.rd },
  { key: 'led', label: 'First Public Action', tip: 'first to publicly announce distrust', good: 'high',
    color: (v, _tot, isRecent) => isRecent
      ? (v > 1 ? COLORS.gn : v > 0 ? COLORS.am : COLORS.rd)
      : (v > 5 ? COLORS.gn : v > 0 ? COLORS.am : COLORS.rd) },
  { key: 'never_acted', label: 'Never Acted', tip: 'peers acted, this store didn\u2019t', good: 'low',
    color: (v) => v === 0 ? COLORS.gn : v <= 1 ? COLORS.am : COLORS.rd },
  { key: 'oversight_coverage', label: 'Bugzilla Coverage', tip: 'CA compliance bugs engaged with governance comments', good: 'high',
    color: (v) => { const n = parseInt(v); return n > 100 ? COLORS.gn : n > 30 ? COLORS.am : n > 0 ? COLORS.rd : COLORS.rd; } },
  { key: 'oversight_substantive', label: 'Substantive Oversight', tip: 'bugs with technical findings — cert/CRL analysis, specific BR citations with evidence; excludes process-only enforcement. % = share of coverage bugs that are substantive.', good: 'high',
    color: (v) => { const n = parseInt(v); return n > 80 ? COLORS.gn : n > 20 ? COLORS.am : n > 0 ? COLORS.rd : COLORS.rd; },
    render: (val, rc) => val > 0 && rc?.oversight_substantive_pct > 0
      ? <>{val}<span style={{ fontSize: 9, fontWeight: 400, opacity: 0.7, marginLeft: 3 }}>({rc.oversight_substantive_pct}%)</span></>
      : val },
  { key: 'proposed', label: 'Ballots Proposed', tip: 'SC + NetSec', good: 'high',
    color: (v, _tot, isRecent) => isRecent
      ? (v > 4 ? COLORS.gn : v > 0 ? COLORS.am : COLORS.rd)
      : (v > 10 ? COLORS.gn : v > 0 ? COLORS.am : COLORS.rd) },
  { key: 'voted', label: 'SC Vote Participation', tip: 'TLS policy \u2014 recent ballots', good: 'high',
    color: (v) => { const n = parseInt(v); return n > 10 ? COLORS.gn : n > 6 ? COLORS.am : COLORS.rd; } },
  { key: 'substantive', label: 'Security-Improving Ballots', tip: 'ballots that improve the WebPKI', good: 'high',
    color: (v, _tot, isRecent) => isRecent
      ? (v > 4 ? COLORS.gn : v > 0 ? COLORS.am : COLORS.rd)
      : (v > 12 ? COLORS.gn : v > 5 ? COLORS.am : COLORS.rd) },
  { key: 'divider' },
  { key: 'owners', label: 'CA Owners Trusted', tip: 'organizations in store \u2014 current', good: 'low',
    color: (v) => v > 70 ? COLORS.rd : v > 55 ? COLORS.am : COLORS.t2 },
  { key: 'roots', label: 'Root Certificates', tip: 'individual roots \u2014 current', good: 'low',
    color: (v) => v > 250 ? COLORS.rd : v > 190 ? COLORS.am : COLORS.t2 },
  { key: 'exclusive', label: 'Exclusive Roots', tip: 'no other store trusts \u2014 current', good: 'low',
    color: (v) => v > 100 ? COLORS.rd : v > 10 ? COLORS.am : COLORS.t2 },
  { key: 'gov', label: 'Gov-Affiliated CAs', tip: 'state-owned / operated \u2014 current', good: 'low',
    color: (v) => v > 18 ? COLORS.rd : v > 14 ? COLORS.am : COLORS.t2 },
  { key: 'dark_matter_excl', label: 'Ungoverned Exclusive CAs', tip: 'CAs exclusive to this store with zero public compliance record \u2014 no Bugzilla filing ever, no cross-program oversight, compliance posture unknown', good: 'low',
    color: (v) => v > 20 ? COLORS.rd : v > 5 ? COLORS.am : v > 0 ? COLORS.t2 : COLORS.gn },
  { key: 'still_trusts', label: 'Still Trusts Removed CAs', tip: 'CAs peers removed \u2014 current', good: 'low',
    color: (v) => v > 2 ? COLORS.rd : v > 0 ? COLORS.am : COLORS.gn },
];

// "Recent" window definitions:
//   Enforcement: distrust events from 2021 onward
//   Oversight:   last 12 quarters of oversight_quarterly
//   Ballots:     ballot_classification.recent (last 50 ballots) + recent_votes (14 ballots) for vote participation
const RECENT_YEAR_CUTOFF = 2021;

/* ── Derived data ── */
function useReportCard(d, isRecent) {
  return useMemo(() => {
    if (!d) return { reportCard: {}, totalEvents: 0, firstDistrustYear: 2011, allEventsTotal: 0 };

    const allEvents = d.distrust_events || [];
    const recentEvents = allEvents.filter(e => (e.year || 0) >= RECENT_YEAR_CUTOFF);
    const events = isRecent ? recentEvents : allEvents;
    const totalEvents = isRecent ? recentEvents.length : (d.enforcement?.chrome?.total || allEvents.length);
    const allEventsTotal = d.enforcement?.chrome?.total || allEvents.length;
    const firstDistrustYear = allEvents.length > 0
      ? Math.min(...allEvents.map(e => e.year || 9999).filter(y => y < 9999))
      : 2011;

    // Recent oversight: sum last 12 quarters per store
    const allQuarters = d.oversight_quarterly || [];
    const recentQuarters = allQuarters.slice(-12);

    const reportCard = {};
    for (const s of STORE_ORDER) {
      const e = d.enforcement?.[s] || {};
      const c = d.program_comment_summary?.[s] || {};
      const p = d.policy_leadership?.programs?.[s] || {};
      const sp = d.store_posture?.[s] || {};
      const bcAll = d.ballot_classification?.browser_summary?.[s] || {};
      const bcRecent = d.ballot_classification?.recent?.browser_summary?.[s] || {};

      // Recent enforcement: count from filtered events
      const acted = isRecent
        ? events.filter(ev => ev[s] !== 'trusted' && ev[s] != null).length
        : (e.acted || 0);
      const led = isRecent
        ? events.filter(ev => ev.leader === s).length
        : (e.initiated || 0);
      const neverActed = totalEvents - acted;

      // Total bugs in corpus for coverage rate denominator
      const totalBugs = d.meta?.bugs_total || 0;

      // Coverage: bugs engaged with genuine governance comments / total bugs
      // Substantive: bugs with technically substantive comments / total bugs
      const coverageBugs = isRecent
        ? (c.recent_bugs_oversight ?? c.bugs_oversight ?? 0)
        : (c.bugs_oversight ?? 0);
      const substantiveBugs = isRecent
        ? (c.recent_bugs_technical_oversight ?? 0)
        : (c.bugs_technical_oversight ?? 0);
      // Percentage of coverage bugs that are technically substantive (vs process-only)
      const substantivePct = coverageBugs > 0 ? Math.round(substantiveBugs / coverageBugs * 100) : 0;

      // Voted: for recent, count yes votes in recent_votes (14 ballots)
      const recentVotes = d.policy_leadership?.recent_votes || [];
      const votedRecent = recentVotes.filter(v => v[s] === 'yes').length;

      const bc = isRecent ? bcRecent : bcAll;

      reportCard[s] = {
        enforcement: `${acted}/${totalEvents}`,
        led,
        never_acted: neverActed,
        oversight_coverage: coverageBugs,
        oversight_substantive: substantiveBugs,
        oversight_substantive_pct: substantivePct,
        proposed: isRecent ? (bcRecent.endorsed || 0) : (p.proposed || 0),
        voted: isRecent
          ? `${votedRecent}/${recentVotes.length}`
          : `${p.voted || 0}/${p.ballots_with_votes || 0}`,
        substantive: bc.substantive || 0,
        // Trust surface metrics are always current snapshot — no time filter applies
        owners: sp.owners || 0,
        roots: sp.roots || 0,
        exclusive: sp.exclusive_count || 0,
        gov: sp.gov_ca_count || 0,
        dark_matter_excl: sp.dark_matter?.exclusive_zero_incident ?? 0,
        still_trusts: (e.still_trusts || []).length,
      };
    }
    return { reportCard, totalEvents, firstDistrustYear, allEventsTotal };
  }, [d, isRecent]);
}

/* ── Main component ── */

const GovernanceRiskView = () => {
  const { rpeData, browserCoverage } = usePipeline();

  if (!rpeData) {
    return (
      <DataPending
        tab="Governance Risk"
        source="fetch_rpe.py → root_program_effectiveness.json"
        description="This tab compares how effectively each root program governs the CAs it trusts. Run: python pipeline/fetch_rpe.py"
      />
    );
  }

  const d = rpeData;
  const [reportCardView, setReportCardView] = useState('recent');
  const isRecentRC = reportCardView === 'recent';
  const { reportCard, totalEvents, firstDistrustYear, allEventsTotal } = useReportCard(d, isRecentRC);

  // First year with incident/oversight data — used in "All time: YYYY–present" labels
  const firstIncidentYear = useMemo(() => {
    const years = (d.coverage_rate_by_year || []).map(r => r.y).filter(Boolean);
    return years.length > 0 ? Math.min(...years) : 2014;
  }, [d]);

  // Governance milestone toggle state
  const [govMilestones, setGovMilestones] = useState(() => {
    const init = {};
    GOVERNANCE_MILESTONES.forEach(m => { init[m.id] = m.defaultOn; });
    return init;
  });
  const toggleGovMilestone = id => setGovMilestones(p => ({ ...p, [id]: !p[id] }));
  const activeGovMilestones = GOVERNANCE_MILESTONES.filter(m => govMilestones[m.id]);
  const allQuarters = d.oversight_quarterly || [];
  const [oversightView, setOversightView] = useState('recent');
  const quarters = oversightView === 'recent' ? allQuarters.slice(-12) : allQuarters;
  const [incidentOversightView, setIncidentOversightView] = useState('recent');
  const [incidentDetectionView, setIncidentDetectionView] = useState('recent');
  const allBugCreation = d.bug_creation_by_year || [];
  const bugCreation = incidentDetectionView === 'recent'
    ? allBugCreation.filter(r => r.y >= RECENT_YEAR_CUTOFF)
    : allBugCreation;
  const allDiscoveryByYear = (d.discovery_methods?.by_year || []);
  const discoveryByYear = incidentDetectionView === 'recent'
    ? allDiscoveryByYear.filter(r => r.y >= RECENT_YEAR_CUTOFF)
    : allDiscoveryByYear;
  const bugTotals = incidentDetectionView === 'recent'
    ? STORE_ORDER.reduce((acc, s) => {
        acc[s] = bugCreation.reduce((sum, y) => sum + (y[s] || 0), 0);
        return acc;
      }, { other: bugCreation.reduce((sum, y) => sum + (y.other || 0), 0) })
    : d.bug_creation_totals || {};
  const maxBugYr = Math.max(...bugCreation.map(y => (y.chrome || 0) + (y.mozilla || 0) + (y.apple || 0) + (y.microsoft || 0)), 1);

  const bgMap = {
    [COLORS.gn]: 'color-mix(in srgb, var(--gn) 18%, transparent)', [COLORS.am]: 'rgba(245,158,11,0.18)',
    [COLORS.rd]: 'color-mix(in srgb, var(--rd) 18%, transparent)', [COLORS.t2]: 'color-mix(in srgb, var(--t2) 6%, transparent)',
  };

  const pcs = d.program_comment_summary || {};
  const enforcement = d.enforcement || {};

  // Per-program stats for KPI cards
  const PROG_LABELS = { chrome: 'Chrome', mozilla: 'Mozilla', apple: 'Apple', microsoft: 'Microsoft' };
  const programStats = ['chrome', 'mozilla', 'apple', 'microsoft'].map(prog => {
    const e = enforcement[prog] || {};
    const p = pcs[prog] || {};
    return {
      prog,
      label: PROG_LABELS[prog],
      color: STORE_COLORS[prog],
      led: e.initiated ?? 0,          // distrust events this program led
      acted: e.acted ?? 0,
      total: e.total ?? 0,
      stillTrusts: (e.still_trusts || []).length,
      comments: p.oversight_comments ?? 0,
      bugs: p.bugs_oversight ?? 0,
      recentBugs: p.recent_bugs_oversight ?? 0,
      dm: d.store_posture?.[prog]?.dark_matter?.exclusive_zero_incident ?? null,
    };
  });

  return (
    <div>
      <TabIntro tabId="governance" quote="Who watches the watchmen?">
        Root programs decide who gets trusted and who gets removed. Not all of them govern with the same
        intensity. This tab compares Chrome, Mozilla, Apple, and Microsoft on enforcement, oversight,
        policy leadership, and trust store size — because a program that trusts more CAs but invests less
        in governance creates risk everyone else absorbs.
      </TabIntro>

      {/* ═══ KEY METRICS — row 1: enforcement leadership ═══ */}
      <div style={statGridStyle}>
        {programStats.map(({ prog, label, led, acted, total, stillTrusts, dm }) => {
          const ledColor = led > 5 ? COLORS.gn : led > 0 ? COLORS.am : COLORS.rd;
          const subParts = [
            `${acted}/${total} enforcement actions`,
            stillTrusts > 0 ? `still trusts ${stillTrusts} removed CA${stillTrusts > 1 ? 's' : ''}` : null,
            dm !== null ? (dm > 0 ? `${dm} ungoverned exclusive CA${dm > 1 ? 's' : ''}` : null) : null,
          ].filter(Boolean);
          return (
            <StatCard key={prog}
              l={`${label} — Led Distrust`}
              v={led === 0 ? '0' : `${led}×`}
              s={subParts.join(' · ') || `${acted}/${total} enforcement actions`}
              c={led === 0 ? (prog === 'microsoft' ? COLORS.rd : COLORS.am) : ledColor}
            />
          );
        })}
      </div>

      {/* ═══ KEY METRICS — row 2: oversight comments (the Microsoft 0 story) ═══ */}
      <div style={statGridStyle}>
        {programStats.map(({ prog, label, comments, bugs }) => (
          <StatCard key={prog}
            l={`${label} — Oversight Comments`}
            v={comments === 0 ? '0' : comments.toLocaleString()}
            s={`${bugs.toLocaleString()} CA compliance bugs engaged, all-time — comments on other CAs\u2019 incidents only, self-incident responses excluded`}
            c={comments === 0 ? COLORS.rd : comments < 100 ? COLORS.am : COLORS.gn}
          />
        ))}
      </div>

      {/* ═══ COVERAGE RATE TREND ═══ */}
      {(d.coverage_rate_by_year || []).length > 0 && (() => {
        const cov = d.coverage_rate_by_year;
        const currentYear = new Date().getFullYear();
        return (
          <Card>
            <CardTitle sub="Percentage of all open CA compliance bugs each program commented on per year. Coverage rate — not raw comment volume — is the correct metric: it accounts for a growing bug corpus. Declining rates mean programs are covering a smaller fraction of incidents each year.">
              Oversight Coverage Rate by Year
            </CardTitle>
            <div style={{ height: 220, marginTop: 12 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={cov} margin={{ left: 0, right: 16, top: 8, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.bd} />
                  <XAxis
                    dataKey="y"
                    type="number"
                    domain={['dataMin', 'dataMax']}
                    tick={{ fill: COLORS.t3, fontSize: 9 }}
                    axisLine={{ stroke: COLORS.bd }}
                    tickLine={false}
                    tickFormatter={v => String(v)}
                  />
                  <YAxis
                    tick={{ fill: COLORS.t3, fontSize: 9 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={v => `${v}%`}
                    domain={[0, 'auto']}
                    width={32}
                  />
                  <Tooltip
                    contentStyle={{ background: COLORS.s2, border: `1px solid ${COLORS.bd}`, borderRadius: 6, fontSize: 11 }}
                    labelStyle={{ color: COLORS.tx, fontWeight: 600, marginBottom: 4 }}
                    formatter={(val, name) => [`${val}%`, name.charAt(0).toUpperCase() + name.slice(1)]}
                    labelFormatter={(y) => {
                      const row = cov.find(r => r.y === y);
                      return `${y}${y === currentYear ? ' (partial)' : ''} — ${row?.total_bugs || 0} bugs`;
                    }}
                  />
                  <Line dataKey="chrome"    stroke={STORE_COLORS.chrome}    strokeWidth={2} dot={false} name="chrome" />
                  <Line dataKey="mozilla"   stroke={STORE_COLORS.mozilla}   strokeWidth={2} dot={false} name="mozilla" />
                  <Line dataKey="apple"     stroke={STORE_COLORS.apple}     strokeWidth={1.5} dot={false} name="apple" strokeDasharray="3 3" />
                  <Line dataKey="microsoft" stroke={STORE_COLORS.microsoft} strokeWidth={1} dot={false} name="microsoft" opacity={0.5} />
                  {(() => {
                    // Track how many milestones share the same year so we can offset labels
                    const yearCount = {};
                    activeGovMilestones.forEach(m => { yearCount[m.year] = (yearCount[m.year] || 0) + 1; });
                    const yearIdx = {};
                    return activeGovMilestones.map(m => {
                      yearIdx[m.year] = (yearIdx[m.year] || 0);
                      const dx = 4 + yearIdx[m.year] * 10;
                      yearIdx[m.year]++;
                      return (
                        <ReferenceLine key={m.id} x={m.year} stroke={m.color}
                          strokeDasharray="3 4" strokeOpacity={0.7} strokeWidth={1.5}
                          label={{ value: m.label, position: 'insideBottomLeft', fill: m.color, fontSize: 7, angle: -90, dy: 4, dx }}
                        />
                      );
                    });
                  })()}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div style={{ display: 'flex', gap: 16, fontSize: 9, color: COLORS.t3, marginTop: 6, flexWrap: 'wrap' }}>
              {['chrome','mozilla','apple','microsoft'].map(p => (
                <span key={p} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 16, height: 2, background: STORE_COLORS[p], borderRadius: 1 }} />
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </span>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              {GOVERNANCE_MILESTONES.map(m => (
                <button key={m.id} onClick={() => toggleGovMilestone(m.id)} style={{
                  display: 'flex', alignItems: 'center', gap: 4,
                  padding: '2px 7px', borderRadius: 4, cursor: 'pointer',
                  fontSize: 9, fontFamily: FONT_SANS,
                  border: `1px solid ${govMilestones[m.id] ? m.color : COLORS.bd}`,
                  background: govMilestones[m.id] ? `${m.color}18` : 'transparent',
                  color: govMilestones[m.id] ? m.color : COLORS.t3,
                  opacity: govMilestones[m.id] ? 1 : 0.6,
                }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: m.color, opacity: govMilestones[m.id] ? 1 : 0.3 }} />
                  {m.label}
                </button>
              ))}
            </div>
            <div style={{ ...footnoteStyle, marginTop: 6 }}>
              Both Chrome and Mozilla cover a declining share of an expanding bug corpus as the total number of CA compliance bugs has grown each year.
              Apple participation has grown in recent years from near zero. Microsoft has remained at zero throughout.
              Pre-2017 years excluded (fewer than 10 bugs/year — not statistically meaningful).
            </div>
          </Card>
        );
      })()}

      {/* ═══ REPORT CARD ═══ */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
          <CardTitle sub="Green = strong. Amber = moderate. Red = weak or concerning. Top: governance activity (higher is better). Bottom: trust surface scope (larger stores need more governance to maintain assurance).">
            Program Report Card
          </CardTitle>
          <div style={{ display: 'flex', gap: 2, background: COLORS.bg, borderRadius: 6, padding: 2, flexShrink: 0 }}>
            {[['recent', 'Recent'], ['all', 'All Time']].map(([v, l]) => (
              <button key={v} onClick={() => setReportCardView(v)} style={{
                padding: '3px 10px', fontSize: 10, fontWeight: reportCardView === v ? 600 : 400, borderRadius: 4,
                cursor: 'pointer', border: 'none', background: reportCardView === v ? COLORS.ac : 'transparent',
                color: reportCardView === v ? COLORS.wh : COLORS.t3,
              }}>{l}</button>
            ))}
          </div>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={{ padding: '8px 6px', width: '30%' }} />
              {STORE_ORDER.map(s => (
                <th key={s} style={{ padding: '8px 6px', textAlign: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                    <Dot store={s} size={10} />
                    <span style={{ fontSize: 12, fontWeight: 700, color: STORE_COLORS[s] }}>{STORE_NAMES[s]}</span>
                  </div>
                </th>
              ))}
            </tr></thead>
            <tbody>
              {METRICS.map((m, i) => {
                if (m.key === 'divider') return (
                  <tr key={i}><td colSpan={5} style={{ padding: '6px 0' }}>
                    <div style={{ borderTop: `1px solid ${COLORS.bl}`, marginTop: 2, paddingTop: 6, fontSize: 8, color: COLORS.t3 }}>
                      TRUST SURFACE <span style={{ color: COLORS.bd, marginLeft: 4 }}>larger surface = more to govern{isRecentRC ? ' \u2014 current snapshot' : ''}</span>
                    </div>
                  </td></tr>
                );
                return (
                  <tr key={m.key}>
                    <td style={{ padding: '8px 6px', borderBottom: `1px solid ${COLORS.bd}` }}>
                      <div style={{ fontSize: 10, color: COLORS.t2, fontWeight: 500 }}>{m.label}</div>
                      <div style={{ fontSize: 8, color: COLORS.t3 }}>{m.tip}</div>
                    </td>
                    {STORE_ORDER.map(s => {
                      const val = reportCard[s]?.[m.key];
                      const col = m.color(val, totalEvents, isRecentRC);
                      const display = m.render ? m.render(val, reportCard[s]) : val;
                      return (
                        <td key={s} style={{
                          padding: '8px 6px', textAlign: 'center', fontFamily: FONT_MONO, fontSize: 13,
                          fontWeight: 700, color: col, background: bgMap[col] || 'transparent',
                          borderBottom: `1px solid ${COLORS.bd}`, borderLeft: `1px solid ${COLORS.bg}`,
                        }}>{display}</td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ ...footnoteStyle, marginTop: 10 }}>
          {isRecentRC ? (
            <><strong style={{ color: COLORS.t2 }}>Recent:</strong>{` enforcement events in the last ~5 years (${totalEvents} of ${allEventsTotal} total), Bugzilla oversight, ballots last 50 SC ballots. Trust surface is always current snapshot. `}</>
          ) : (
            `Enforcement: ${totalEvents} events since ${firstDistrustYear}. Bugzilla Coverage = unique CA compliance bugs engaged with genuine governance comments. Substantive Oversight = bugs with technically substantive comments (cert/CRL analysis, policy findings) — excludes process enforcement (survey notices, CCADB reminders, status requests). LLM-classified. Ballots: SC (${d.policy_leadership?.by_working_group?.server_certificate?.total_ballots || 0}) + NS (${d.policy_leadership?.by_working_group?.network_security?.total_ballots || 0}), all time. `
          )}
          Store size reflects policy philosophy, not just governance quality: Chrome is deliberately selective (value must exceed risk, only one new CA accepted),
          Mozilla is the fastest gateway for new CAs, Apple is highly selective, and Microsoft processes root rollovers quickly.
          A larger store is not automatically worse — but it does require proportionally more governance activity to maintain assurance.
        </div>
      </Card>

      {/* ═══ OVERSIGHT TREND ═══ */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
          <CardTitle sub="Quarterly comment volume per program — shows trend and continuity risk. Uses raw substantive comment counts (pre-LLM filter) for historical consistency. Faded bars = single-person quarters (key-person dependency).">
            Oversight Trend and Concentration Risk
          </CardTitle>
          <div style={{ display: 'flex', gap: 2, background: COLORS.bg, borderRadius: 6, padding: 2, flexShrink: 0 }}>
            {[['recent', 'Recent'], ['all', 'All Time']].map(([v, l]) => (
              <button key={v} onClick={() => setOversightView(v)} style={{
                padding: '3px 10px', fontSize: 10, fontWeight: oversightView === v ? 600 : 400, borderRadius: 4,
                cursor: 'pointer', border: 'none', background: oversightView === v ? COLORS.ac : 'transparent',
                color: oversightView === v ? COLORS.wh : COLORS.t3,
              }}>{l}</button>
            ))}
          </div>
        </div>
        {STORE_ORDER.map(prog => {
          const vals = quarters.map(q => q[`${prog}_comments`] || 0);
          const people = quarters.map(q => q[`${prog}_people`] || 0);
          const progPeak = Math.max(...vals, 1);
          const peakQ = quarters[vals.indexOf(progPeak)]?.quarter || '';
          const current = vals[vals.length - 1] || 0;
          const conc = d.oversight_concentration?.[prog] || {};
          const barH = 36;
          return (
            <div key={prog} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: `1px solid ${COLORS.bd}` }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Dot store={prog} size={8} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: STORE_COLORS[prog] }}>{STORE_NAMES[prog]}</span>
                </div>
                <div style={{ display: 'flex', gap: 16, fontSize: 9, fontFamily: FONT_MONO, color: COLORS.t3 }}>
                  <span>now <span style={{ color: COLORS.tx, fontWeight: 600 }}>{current}</span>/qtr</span>
                  <span>peak <span style={{ color: COLORS.tx, fontWeight: 600 }}>{progPeak}</span> <span style={{ fontSize: 7 }}>({peakQ})</span></span>
                  {conc.unique_contributors > 0 && <span>{conc.unique_contributors} people · top1 <span style={{ color: conc.top_contributor_pct > 80 ? COLORS.rd : conc.top_contributor_pct > 50 ? COLORS.am : COLORS.gn, fontWeight: 600 }}>{conc.top_contributor_pct}%</span></span>}
                </div>
              </div>
              <div style={{ position: 'relative' }}>
                <div style={{ display: 'flex', height: barH + 12, alignItems: 'flex-end', gap: 1 }}>
                  {vals.map((v, i) => {
                    const h = progPeak > 0 ? (v / progPeak) * barH : 0;
                    const singlePerson = people[i] <= 1 && v > 0;
                    return (
                      <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        {v > 0 && h > 14 && <span style={{ fontSize: 6, fontFamily: FONT_MONO, color: COLORS.t3, marginBottom: 1 }}>{v}</span>}
                        <div style={{
                          width: '100%', height: Math.max(h, v > 0 ? 2 : 0),
                          background: STORE_COLORS[prog],
                          opacity: singlePerson ? 0.4 : 0.85,
                          borderRadius: '2px 2px 0 0',
                          borderBottom: singlePerson && v > 3 ? `2px solid ${COLORS.rd}` : 'none',
                        }} />
                      </div>
                    );
                  })}
                </div>
                {/* Milestone overlay ticks */}
                {activeGovMilestones.map(m => {
                  // Convert milestone year (float) to quarter string e.g. 2020.25 -> "2020-Q2"
                  const yr = Math.floor(m.year);
                  const qNum = Math.round((m.year - yr) * 4) + 1;
                  const qStr = `${yr}-Q${Math.min(qNum, 4)}`;
                  const idx = quarters.findIndex(q => q.quarter === qStr);
                  if (idx < 0) return null;
                  const leftPct = ((idx + 0.5) / quarters.length) * 100;
                  return (
                    <div key={m.id} title={m.label} style={{
                      position: 'absolute', left: `${leftPct}%`, top: 0,
                      width: 1.5, height: barH + 12,
                      background: m.color, opacity: 0.6,
                      pointerEvents: 'none',
                    }} />
                  );
                })}
              </div>
              {/* Tiny scale indicator */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', fontSize: 7, color: COLORS.t3, marginTop: 1, opacity: 0.5 }}>
                max {progPeak}
              </div>
            </div>
          );
        })}
        {quarters.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 7, color: COLORS.t3, marginTop: -4 }}>
            <span>{quarters[0]?.quarter}</span>
            {quarters.length > 8 && <span>{quarters[Math.floor(quarters.length / 4)]?.quarter}</span>}
            <span>{quarters[Math.floor(quarters.length / 2)]?.quarter}</span>
            {quarters.length > 8 && <span>{quarters[Math.floor(quarters.length * 3 / 4)]?.quarter}</span>}
            <span>{quarters[quarters.length - 1]?.quarter}</span>
          </div>
        )}
        <div style={{ display: 'flex', gap: 12, fontSize: 8, color: COLORS.t3, marginTop: 8 }}>
          <span><span style={{ display: 'inline-block', width: 12, height: 8, borderRadius: 2, background: COLORS.t2, opacity: 0.85, marginRight: 3, verticalAlign: 'middle' }} />Multi-contributor</span>
          <span><span style={{ display: 'inline-block', width: 12, height: 8, borderRadius: 2, background: COLORS.t2, opacity: 0.4, marginRight: 3, verticalAlign: 'middle', borderBottom: `2px solid ${COLORS.rd}` }} />Single contributor</span>
          <span style={{ marginLeft: 'auto', color: COLORS.t3 }}>Note: counts here are unfiltered quarterly totals — higher than Report Card figures which exclude admin noise via LLM classification. Use this chart for trend direction, not absolute comparison.</span>
        </div>
      </Card>

      {/* ═══ NOTABLE GAPS ═══ */}
      <Card>
        <CardTitle sub="Where root store decisions diverge — on inclusion or enforcement.">Notable Inclusion and Trust Gaps</CardTitle>
        <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead><tr style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
            <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'left' }}>CA</th>
            <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'right' }}>Certs</th>
            {STORE_ORDER.map(s => <th key={s} style={{ padding: '5px', textAlign: 'center' }}><Dot store={s} size={6} /></th>)}
            <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'right' }}>Gap</th>
          </tr></thead>
          <tbody>
            {(d.notable_gaps?.current || []).length > 0 && (
              <tr><td colSpan={8} style={{ padding: '6px 5px 3px', fontSize: 8, color: COLORS.am, fontWeight: 600, textTransform: 'uppercase' }}>Current</td></tr>
            )}
            {(d.notable_gaps?.current || []).slice(0, 6).map(g => (
              <tr key={g.ca} style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                <td style={{ padding: '4px 5px', color: COLORS.tx, fontWeight: 500 }}>{g.ca.length > 25 ? g.ca.slice(0, 25) + '…' : g.ca} (#{g.rank})</td>
                <td style={{ padding: '4px 5px', fontFamily: FONT_MONO, fontSize: 9, color: COLORS.t2, textAlign: 'right' }}>{g.certs >= 1000 ? `${Math.round(g.certs / 1000)}K` : g.certs}</td>
                {STORE_ORDER.map(s => <td key={s} style={{ padding: '4px 5px', textAlign: 'center', fontSize: 11, fontWeight: 700, color: g.stores?.[s] === 'included' ? COLORS.gn : COLORS.rd }}>{g.stores?.[s] === 'included' ? '\u2713' : '\u2717'}</td>)}
                <td style={{ padding: '4px 5px', fontFamily: FONT_MONO, fontSize: 9, textAlign: 'right', color: COLORS.am }}>{g.wait_years ? `${g.wait_years}yr` : '\u2014'}</td>
              </tr>
            ))}
            {(d.notable_gaps?.distrust_divergences || []).length > 0 && (
              <>
                <tr><td colSpan={8} style={{ padding: '8px 5px 3px', fontSize: 8, color: COLORS.rd, fontWeight: 600, textTransform: 'uppercase' }}>Distrust Divergences</td></tr>
                {d.notable_gaps.distrust_divergences.map(g => (
                  <tr key={g.ca} style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                    <td colSpan={2} style={{ padding: '4px 5px', color: COLORS.tx, fontWeight: 500 }}>{g.ca}</td>
                    {STORE_ORDER.map(s => <td key={s} style={{ padding: '4px 5px', textAlign: 'center', fontSize: 11, fontWeight: 700, color: (g.still_trusted_by || []).includes(s) ? COLORS.rd : COLORS.gn }}>{(g.still_trusted_by || []).includes(s) ? '\u2717' : '\u2713'}</td>)}
                    <td />
                  </tr>
                ))}
              </>
            )}
          </tbody>
        </table>
        </div>
      </Card>

      {/* ═══ INCLUSION VELOCITY ═══ */}
      {d.inclusion_velocity?.mozilla_stats && (() => {
        const iv = d.inclusion_velocity;
        const stats = iv.mozilla_stats;
        const pending = (iv.mozilla_pending || []).sort((a, b) => b.days_waiting - a.days_waiting);
        const newOrg = stats.new_org || {};
        const existingCa = stats.existing_ca || {};
        return (
          <Card>
            <CardTitle sub={`${stats.pending_count} requests in Mozilla's inclusion pipeline — ${newOrg.pending_count || 0} new organizations, ${existingCa.pending_count || 0} existing CAs adding roots.`}>
              Inclusion Velocity (Mozilla)
            </CardTitle>
            <div style={statGridStyle}>
              <StatCard l="New Org — Median" v={`${newOrg.median_days || 0}d`} s={`${((newOrg.median_days || 0) / 365).toFixed(1)}y · ${newOrg.pending_count || 0} pending`} c={(newOrg.median_days || 0) > 730 ? COLORS.rd : (newOrg.median_days || 0) > 365 ? COLORS.am : COLORS.gn} />
              <StatCard l="Existing CA — Median" v={`${existingCa.median_days || 0}d`} s={`${((existingCa.median_days || 0) / 365).toFixed(1)}y · ${existingCa.pending_count || 0} pending`} c={(existingCa.median_days || 0) > 365 ? COLORS.am : COLORS.gn} />
              <StatCard l="Longest Pending" v={`${stats.longest_pending_days}d`} s={`${(stats.longest_pending_days / 365).toFixed(1)} years`} c={COLORS.rd} />
              <StatCard l="Pending" v={stats.pending_count} s={`${stats.completed_count} completed (2020+)`} c={COLORS.ac} />
            </div>
            {pending.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                  <thead><tr style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                    <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'left', textTransform: 'uppercase', letterSpacing: '0.04em' }}>CA</th>
                    <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'left', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Type</th>
                    <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'right', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Filed</th>
                    <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'right', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Waiting</th>
                    <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'left', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Stage</th>
                  </tr></thead>
                  <tbody>
                    {pending.slice(0, 15).map(p => (
                      <tr key={p.bug} style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                        <td style={{ padding: '4px 5px', color: COLORS.tx, fontWeight: 500, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          <a href={`https://bugzilla.mozilla.org/show_bug.cgi?id=${p.bug}`} target="_blank" rel="noopener noreferrer" style={{ color: COLORS.tx, textDecoration: 'none' }}>{p.ca}</a>
                        </td>
                        <td style={{ padding: '4px 5px', fontSize: 8, color: p.request_type === 'new_org' ? COLORS.am : COLORS.t3, whiteSpace: 'nowrap' }}>
                          {p.request_type === 'new_org' ? 'new org' : 'add root'}
                        </td>
                        <td style={{ padding: '4px 5px', fontFamily: FONT_MONO, fontSize: 9, color: COLORS.t3, textAlign: 'right' }}>{p.filed}</td>
                        <td style={{ padding: '4px 5px', fontFamily: FONT_MONO, fontSize: 9, textAlign: 'right', color: p.days_waiting > 1000 ? COLORS.rd : p.days_waiting > 365 ? COLORS.am : COLORS.t2 }}>
                          {p.days_waiting}d ({(p.days_waiting / 365).toFixed(1)}y)
                        </td>
                        <td style={{ padding: '4px 5px', fontSize: 9, color: COLORS.t3 }}>{p.stage || '\u2014'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {pending.length > 15 && (
                  <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 4 }}>
                    Showing 15 of {pending.length} pending applications (sorted by wait time)
                  </div>
                )}
              </div>
            )}
            <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 6, lineHeight: 1.4 }}>
              New org = first-ever Mozilla inclusion request. Add root = existing trusted CA adding new or replacement roots. Wait times from Bugzilla bug creation. Mozilla is shown because it is the only program with a fully public, trackable inclusion pipeline.
            </div>
          </Card>
        );
      })()}

      {/* ═══ ENFORCEMENT ═══ */}
      <Card>
        <CardTitle sub={`${allEventsTotal} events since ${firstDistrustYear} where root programs acted to protect users.`}>Actions to Protect Users</CardTitle>
        <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead><tr style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
            <th style={{ padding: '4px 5px', color: COLORS.t3, fontSize: 8, textAlign: 'left' }}>CA</th>
            <th style={{ padding: '4px 5px', color: COLORS.t3, fontSize: 8, textAlign: 'center' }}>Year</th>
            {STORE_ORDER.map(s => <th key={s} style={{ padding: '4px 5px', textAlign: 'center' }}><Dot store={s} size={6} /></th>)}
            <th style={{ padding: '4px 5px', color: COLORS.t3, fontSize: 8, textAlign: 'left' }}>First*</th>
          </tr></thead>
          <tbody>
            {(d.distrust_events || []).map(ev => (
              <tr key={ev.ca} style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                <td style={{ padding: '3px 5px', color: COLORS.tx, fontWeight: 500 }}>{ev.ca}</td>
                <td style={{ padding: '3px 5px', fontFamily: FONT_MONO, fontSize: 9, color: COLORS.t3, textAlign: 'center' }}>{ev.year}</td>
                {STORE_ORDER.map(s => (
                  <td key={s} style={{ padding: '3px 5px', textAlign: 'center', fontSize: 10, fontWeight: 700, color: ev[s] === 'trusted' ? COLORS.rd : COLORS.gn }}>
                    {ev[s] === 'trusted' ? '\u2717' : ev[s] === 'constrained' ? '\u25D0' : '\u2713'}
                  </td>
                ))}
                <td style={{ padding: '3px 5px', fontSize: 9, color: STORE_COLORS[ev.leader], fontWeight: 600 }}>{STORE_NAMES[ev.leader]}</td>
              </tr>
            ))}
            <tr style={{ borderTop: `2px solid ${COLORS.bd}` }}>
              <td style={{ padding: '5px', fontWeight: 600, color: COLORS.t2, fontSize: 9 }}>TOTAL</td><td />
              {STORE_ORDER.map(s => {
                const acted = d.enforcement?.[s]?.acted || 0;
                return <td key={s} style={{ padding: '5px', textAlign: 'center', fontFamily: FONT_MONO, fontWeight: 700, fontSize: 11, color: acted >= totalEvents ? COLORS.gn : acted >= totalEvents - 1 ? COLORS.am : COLORS.rd }}>{acted}/{totalEvents}</td>;
              })}
              <td />
            </tr>
          </tbody>
        </table>
        </div>
        <div style={{ fontSize: 9, color: COLORS.t3, marginTop: 6, lineHeight: 1.4 }}>
          * "First" = first program to publicly announce action. Apple often acts before other programs but does not announce on Bugzilla or mailing lists — their actions may predate public announcements from other programs.
        </div>
      </Card>
      <Card>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
          <CardTitle sub={`Oversight = genuine governance comments on other CAs' compliance bugs. Self-incident = responding to your own CA's issues. ${d.meta?.bugs_with_comments || 0} bugs, ${(d.meta?.total_comments_analyzed || 0).toLocaleString()} comments after LLM admin filtering (${(d.meta?.total_comments_raw || 0).toLocaleString()} raw).`}>
            Incident Oversight
          </CardTitle>
          <div style={{ display: 'flex', gap: 2, background: COLORS.bg, borderRadius: 6, padding: 2, flexShrink: 0 }}>
            {[['recent', 'Recent'], ['all', 'All Time']].map(([v, l]) => (
              <button key={v} onClick={() => setIncidentOversightView(v)} style={{
                padding: '3px 10px', fontSize: 10, fontWeight: incidentOversightView === v ? 600 : 400, borderRadius: 4,
                cursor: 'pointer', border: 'none', background: incidentOversightView === v ? COLORS.ac : 'transparent',
                color: incidentOversightView === v ? COLORS.wh : COLORS.t3,
              }}>{l}</button>
            ))}
          </div>
        </div>
        {(() => {
          // Show three segments: technical oversight (bright), process oversight (mid), self-incident (faded)
          const isRO = incidentOversightView === 'recent';
          const pcs = d.program_comment_summary || {};
          const totalBugs = d.meta?.bugs_total || 0;

          const windowMax = Math.max(...STORE_ORDER.map(s => {
            const cs = pcs[s] || {};
            const cov = isRO ? (cs.recent_bugs_oversight ?? cs.bugs_oversight ?? 0) : (cs.bugs_oversight ?? 0);
            const si = cs.self_incident_comments || 0;
            return cov + si;
          }), 1);

          return STORE_ORDER.map(s => {
            const cs = pcs[s] || {};
            const covBugs = isRO ? (cs.recent_bugs_oversight ?? cs.bugs_oversight ?? 0) : (cs.bugs_oversight ?? 0);
            const techBugs = isRO ? (cs.recent_bugs_technical_oversight ?? 0) : (cs.bugs_technical_oversight ?? 0);
            const procBugs = covBugs - techBugs;  // process-only enforcement bugs
            const sic = cs.self_incident_comments || 0;
            const covPct = Math.round(covBugs / totalBugs * 100);
            return (
              <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                <div style={{ width: 66, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Dot store={s} size={6} />
                  <span style={{ fontSize: 9, color: STORE_COLORS[s], fontWeight: 500 }}>{STORE_NAMES[s]}</span>
                </div>
                <div style={{ flex: 1, height: 20, display: 'flex', borderRadius: 4, overflow: 'hidden' }}>
                  {techBugs > 0 && <div style={{ width: `${(techBugs / windowMax) * 100}%`, background: STORE_COLORS[s], opacity: 0.9, display: 'flex', alignItems: 'center', paddingLeft: techBugs > 20 ? 5 : 2 }}>
                    {techBugs > 20 && <span style={{ fontSize: 8, color: COLORS.wh, fontFamily: FONT_MONO, fontWeight: 700 }}>{techBugs}</span>}
                  </div>}
                  {procBugs > 0 && <div style={{ width: `${(procBugs / windowMax) * 100}%`, background: STORE_COLORS[s], opacity: 0.4 }} />}
                  {sic > 0 && <div style={{ width: `${(sic / windowMax) * 100}%`, background: STORE_COLORS[s], opacity: 0.15 }} />}
                </div>
                <span style={{ fontSize: 9, fontFamily: FONT_MONO, width: 50, textAlign: 'right', fontWeight: 600, color: covBugs > 0 ? COLORS.t2 : COLORS.rd }}>
                  {covBugs}<span style={{ fontWeight: 400, color: COLORS.t3 }}> bugs</span>
                </span>
              </div>
            );
          });
        })()}
        <div style={{ display: 'flex', gap: 12, fontSize: 8, color: COLORS.t3, marginTop: 4 }}>
          <span><span style={{ display: 'inline-block', width: 10, height: 8, borderRadius: 2, background: COLORS.t2, opacity: 0.9, marginRight: 3, verticalAlign: 'middle' }} />Technical findings</span>
          <span><span style={{ display: 'inline-block', width: 10, height: 8, borderRadius: 2, background: COLORS.t2, opacity: 0.4, marginRight: 3, verticalAlign: 'middle' }} />Process enforcement</span>
          <span><span style={{ display: 'inline-block', width: 10, height: 8, borderRadius: 2, background: COLORS.t2, opacity: 0.15, marginRight: 3, verticalAlign: 'middle' }} />Self-incident</span>
        </div>
        <div style={{ fontSize: 9, color: COLORS.t3, marginTop: 8, lineHeight: 1.4, borderTop: `1px solid ${COLORS.bd}`, paddingTop: 6 }}>
          {incidentOversightView === 'recent' ? (
            <><strong style={{ color: COLORS.t2 }}>Recent:</strong>{' '}</>
          ) : (
            `All time: ${firstIncidentYear}–present. `
          )}
          Bar = unique bugs engaged. Bright = technical findings. Mid = process enforcement. Faded = self-incident (own CA). LLM-classified; administrative noise excluded. Public Bugzilla only — private governance not captured.
        </div>
      </Card>

      {/* ═══ INCIDENT DETECTION ═══ */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
          <CardTitle sub="Who files Bugzilla bugs, and how were incidents actually discovered? Filing a bug is a process step — the actual discovery may have been by a researcher, auditor, root program, or the CA's own monitoring.">
            Incident Detection
          </CardTitle>
          <div style={{ display: 'flex', gap: 2, background: COLORS.bg, borderRadius: 6, padding: 2, flexShrink: 0 }}>
            {[['recent', 'Recent'], ['all', 'All Time']].map(([v, l]) => (
              <button key={v} onClick={() => setIncidentDetectionView(v)} style={{
                padding: '3px 10px', fontSize: 10, fontWeight: incidentDetectionView === v ? 600 : 400, borderRadius: 4,
                cursor: 'pointer', border: 'none', background: incidentDetectionView === v ? COLORS.ac : 'transparent',
                color: incidentDetectionView === v ? COLORS.wh : COLORS.t3,
              }}>{l}</button>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', height: 90, alignItems: 'flex-end', gap: 2 }}>
          {bugCreation.map(y => {
            const total = STORE_ORDER.reduce((a, s) => a + (y[s] || 0), 0) + (y.other || 0);
            return (
              <div key={y.y} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                {total > 0 && <span style={{ fontSize: 7, fontFamily: FONT_MONO, color: COLORS.t3, marginBottom: 1 }}>{total}</span>}
                <div style={{ width: '100%', height: 70, display: 'flex', flexDirection: 'column-reverse' }}>
                  {STORE_ORDER.map(s => {
                    const v = y[s] || 0;
                    if (v === 0) return null;
                    return <div key={s} style={{ width: '100%', height: (v / maxBugYr) * 70, background: STORE_COLORS[s], opacity: 0.8 }} />;
                  })}
                </div>
                <span style={{ fontSize: 7, color: COLORS.t3, marginTop: 2 }}>{String(y.y).slice(2)}</span>
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 8, color: COLORS.t3 }}>
          {STORE_ORDER.map(s => (
            <span key={s}><Dot store={s} size={5} /> <span style={{ color: STORE_COLORS[s], fontWeight: 600 }}>{bugTotals[s] || 0}</span> {STORE_NAMES[s]}</span>
          ))}
          <span style={{ marginLeft: 'auto' }}>{(bugTotals.other || 0).toLocaleString()} CA-filed</span>
        </div>

        {/* Discovery method breakdown */}
        {d.discovery_methods && (() => {
          const dm = d.discovery_methods;
          const isRecDet = incidentDetectionView === 'recent';
          // Recompute totals from filtered by_year rows in recent mode
          const t = isRecDet
            ? discoveryByYear.reduce((acc, y) => {
                for (const k of ['self_detected','external_researcher','root_program','community','audit','unknown']) {
                  acc[k] = (acc[k] || 0) + (y[k] || 0);
                }
                return acc;
              }, {})
            : dm.totals || {};
          const total = Object.values(t).reduce((a, v) => a + v, 0);
          const unknownPct = total > 0 ? Math.round((t.unknown || 0) / total * 100) : 100;
          const DISC_COLORS = {
            self_detected: COLORS.gn, external_researcher: COLORS.am, root_program: COLORS.ac,
            community: COLORS.pu, audit: COLORS.g5, unknown: '#1f2937',
          };
          const DISC_LABELS = {
            self_detected: 'Self-Detected', external_researcher: 'Externally Reported',
            root_program: 'Root Program', community: 'Community', audit: 'Audit', unknown: 'Unclassified',
          };
          const DISC_ORDER = ['self_detected', 'external_researcher', 'root_program', 'community', 'audit', 'unknown'];

          return (
            <div style={{ marginTop: 16, paddingTop: 12, borderTop: `1px solid ${COLORS.bd}` }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: COLORS.tx, marginBottom: 4 }}>How Were Incidents Discovered?</div>
              {unknownPct > 80 ? (
                <div style={{ fontSize: 9, color: COLORS.t3, lineHeight: 1.5, padding: '8px 0' }}>
                  Classification in progress — collecting incident report text from Bugzilla comments.{' '}
                  {total - (t.unknown || 0)} of {total} bugs classified so far ({100 - unknownPct}%).
                  Discovery categories: self-detected (CA's own monitoring), externally reported (researcher/customer),
                  root program (browser found it), community (CT logs, linting tools), and audit.
                </div>
              ) : (
                <>
                  {/* Stacked bar showing discovery method proportions */}
                  <div style={{ display: 'flex', height: 28, borderRadius: 4, overflow: 'hidden', marginBottom: 6 }}>
                    {DISC_ORDER.map(m => {
                      const v = t[m] || 0;
                      if (v === 0) return null;
                      return (
                        <div key={m} title={`${DISC_LABELS[m]}: ${v} (${Math.round(v / total * 100)}%)`}
                          style={{ width: `${(v / total) * 100}%`, background: DISC_COLORS[m], opacity: 0.85 }} />
                      );
                    })}
                  </div>
                  {/* Per-year breakdown */}
                  {discoveryByYear.length > 0 && (
                    <div style={{ display: 'flex', height: 60, alignItems: 'flex-end', gap: 2, marginBottom: 4 }}>
                      {discoveryByYear.map(y => {
                        const yTotal = y.total || 1;
                        return (
                          <div key={y.y} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                            <span style={{ fontSize: 7, fontFamily: FONT_MONO, color: COLORS.t3, marginBottom: 1 }}>{yTotal}</span>
                            <div style={{ width: '100%', height: 40, display: 'flex', flexDirection: 'column-reverse' }}>
                              {DISC_ORDER.filter(m => m !== 'unknown').map(m => {
                                const v = y[m] || 0;
                                if (v === 0) return null;
                                return <div key={m} style={{ width: '100%', height: (v / yTotal) * 40, background: DISC_COLORS[m], opacity: 0.85 }} />;
                              })}
                            </div>
                            <span style={{ fontSize: 7, color: COLORS.t3, marginTop: 2 }}>{String(y.y).slice(2)}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 8, color: COLORS.t3 }}>
                    {DISC_ORDER.map(m => {
                      const v = t[m] || 0;
                      if (v === 0) return null;
                      return (
                        <span key={m}>
                          <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 2, background: DISC_COLORS[m], opacity: 0.85, marginRight: 3, verticalAlign: 'middle' }} />
                          {DISC_LABELS[m]} <span style={{ fontFamily: FONT_MONO, fontWeight: 600 }}>{v}</span>
                        </span>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          );
        })()}
        <div style={{ fontSize: 9, color: COLORS.t3, marginTop: 8, lineHeight: 1.4, borderTop: `1px solid ${COLORS.bd}`, paddingTop: 6 }}>
          {incidentDetectionView === 'recent' ? (
            <><strong style={{ color: COLORS.t2 }}>Recent:</strong>{' Bug filing totals and discovery method proportions reflect this window only. '}</>
          ) : (
            `All time: ${firstIncidentYear}–present. `
          )}
          Bug filing counts show who opened the Bugzilla bug, not who discovered the issue. A root program filing a bug may be splitting an existing incident into per-CA threads rather than independently discovering a new compliance failure.
        </div>
      </Card>

      {/* ═══ VOTE MATRIX ═══ */}
      <Card>
        <div style={{ overflowX: 'auto' }}>
        <CardTitle sub="How each root program voted on recent Server Certificate ballots.">Recent SC Ballot Votes</CardTitle>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead><tr style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
            <th style={{ padding: '4px 5px', color: COLORS.t3, fontSize: 8, textAlign: 'left' }}>Ballot</th>
            {STORE_ORDER.map(s => <th key={s} style={{ padding: '4px 5px', textAlign: 'center' }}><Dot store={s} size={6} /></th>)}
          </tr></thead>
          <tbody>
            {(d.policy_leadership?.recent_votes || []).map(v => (
              <tr key={v.id} style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                <td style={{ padding: '3px 5px', fontSize: 9 }}><span style={{ fontFamily: FONT_MONO, color: COLORS.t3, marginRight: 4 }}>{v.id}</span><span style={{ color: COLORS.tx }}>{v.title}</span></td>
                {STORE_ORDER.map(s => <td key={s} style={{ padding: '3px 5px', textAlign: 'center', fontSize: 10, fontWeight: 700, color: v[s] === 'yes' ? COLORS.gn : COLORS.t3 }}>{v[s] === 'yes' ? '\u2713' : '\u2014'}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Card>

      {/* ═══ CROSS-WG ═══ */}
      <Card>
        <CardTitle sub="Ballot proposals and endorsements by root program and CA organization per working group. Root programs are expected to lead — not just enforce — standards development. Low proposal counts from browsers signal reactive rather than proactive governance.">Policy Engagement by Working Group</CardTitle>
        <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead><tr style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
            <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'left' }}>Working Group</th>
            <th style={{ padding: '5px', color: COLORS.t3, fontSize: 8, textAlign: 'center' }}>N</th>
            {STORE_ORDER.map(s => <th key={s} style={{ padding: '5px', textAlign: 'center' }}><Dot store={s} size={6} /></th>)}
          </tr></thead>
          <tbody>
            {Object.entries(d.policy_leadership?.by_working_group || {}).map(([key, wg]) => (
              <tr key={key} style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                <td style={{ padding: '5px', color: COLORS.tx, fontSize: 9, fontWeight: 500 }}>{key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</td>
                <td style={{ padding: '5px', textAlign: 'center', fontFamily: FONT_MONO, fontSize: 9, color: COLORS.t3 }}>{wg.total_ballots}</td>
                {STORE_ORDER.map(s => {
                  const p = wg.programs?.[s] || {};
                  const prop = p.proposed || 0;
                  const end = p.endorsed || 0;
                  return <td key={s} style={{ padding: '5px', textAlign: 'center', fontSize: 9, fontFamily: FONT_MONO }}>
                    {prop + end > 0 ? <span style={{ color: prop > 0 ? COLORS.tx : COLORS.t2 }}>{prop}<span style={{ color: COLORS.t3 }}>+{end}</span></span> : <span style={{ color: COLORS.t3 }}>{'\u2014'}</span>}
                  </td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Card>

      {/* ═══ METHODOLOGY ═══ */}
      <MethodologyCard>
        <MethodologyItem label="Bugzilla Oversight">
          Measures root program governance participation on CA compliance incident bugs. Two metrics:
          "Bugzilla Coverage" = unique bugs where the program left at least one genuine governance comment, divided by total bugs in corpus ({d.meta?.bugs_total || 0}).
          "Substantive Oversight" = unique bugs where the program left a technically substantive comment — certificate or CRL analysis, specific BR/RFC citation with evidence, scope quantification, or root cause identification. Excludes process enforcement only comments (overdue notices, follow-up requests, housekeeping directives with no technical content).
          {' '}Single-pass LLM classification (claude-haiku) returns both fields simultaneously: governance (genuine vs administrative) and technical (analysis vs process enforcement). {(d.meta?.total_comments_raw || 0).toLocaleString()} raw comments → {(d.meta?.total_comments_analyzed || 0).toLocaleString()} substantive after governance filter.
          Comment authors attributed by email domain. Bot accounts excluded. Public Bugzilla only — private governance not captured.
          Microsoft operates Microsoft PKI Services (a publicly trusted CA); all their governance comments are self-incident responses. Their 0 coverage reflects genuine absence of public oversight engagement, not a data artifact.
          Note: the Oversight Trend chart uses unfiltered quarterly comment totals for historical continuity — its values are higher than the LLM-filtered figures in the Report Card. Use the trend chart for directional analysis, not absolute comparison.
        </MethodologyItem>
        <MethodologyItem label="Enforcement">
          {totalEvents} distrust events curated from root program announcements, Bugzilla threads, CCADB status changes, and Apple support documents.
          "First" = first program to publicly announce action. "Never Acted" = CCADB still shows trust while peers have removed the CA.
          Each root program discloses enforcement differently: Chrome publishes blog posts and policy announcements. Mozilla uses Bugzilla threads and the mozilla.dev.security.policy mailing list. Microsoft publishes monthly CTL deployment notices.
          Apple publishes support documents with SHA-256 hashes but does not announce on Bugzilla or mailing lists — their actions may predate other programs' public announcements. "First" is biased toward programs that announce publicly.
        </MethodologyItem>
        <MethodologyItem label="Incident Detection">
          Bug filing counts reflect who opened the Bugzilla bug, not who discovered the underlying issue.
          A root program filing a bug may be splitting an existing incident into per-CA tracking threads rather than independently discovering a new compliance failure.
          The "How Were Incidents Discovered?" breakdown classifies actual discovery method from the incident report text using keyword patterns: self-detected (CA's own monitoring), externally reported (researcher or customer), root program, community (CT logs, linting tools), and audit.
        </MethodologyItem>
        <MethodologyItem label="Policy Leadership">
          Ballot proposers and endorsers scraped from cabforum.org across {Object.keys(d.policy_leadership?.by_working_group || {}).length} working groups ({Object.values(d.policy_leadership?.by_working_group || {}).reduce((a, w) => a + (w.total_ballots || 0), 0)} total ballots).
          Vote participation from the {d.policy_leadership?.programs?.chrome?.ballots_with_votes || 0} most recent SC ballots with published results.
          "Security-Improving Ballots" = ballots classified as substantive (validation improvement, security modernization, transparency) rather than procedural. Classification is title-based using keyword matching.
          Vote participation includes yes, no, and abstain. Abstaining or not voting may reflect policy disagreement, a deliberate choice not to legitimize a ballot, or capacity constraints — it is not inherently a governance failure.
          Recent window = last 50 ballots across all working groups.
        </MethodologyItem>
        <MethodologyItem label="Ungoverned Exclusive CAs">
          A CA is "ungoverned" for this metric if it has zero entries in the public Bugzilla CA Certificate Compliance record — no incident reports filed, no governance comments received. A CA is "exclusive" if it appears in only one trust store and therefore faces no cross-program oversight pressure.
          The combination — exclusive to one store AND no public compliance record — means the CA's compliance posture is entirely opaque to the public ecosystem. Its certificates are trusted by operating systems and browsers, but nothing in the public record describes what it does, whether it has ever had a compliance failure, or whether any root program has ever scrutinized it.
          {(() => {
            const sp = d.store_posture || {};
            const ms = sp.microsoft?.dark_matter || {};
            const moz = sp.mozilla?.dark_matter || {};
            const msZero = ms.exclusive_zero_incident || 0;
            const msExcl = ms.exclusive_cas || 0;
            const msPct = msExcl > 0 ? Math.round(msZero / msExcl * 100) : 0;
            const mozZero = moz.exclusive_zero_incident || 0;
            return ` Microsoft has ${msZero} such CAs (${msPct}% of its ${msExcl} exclusive CAs). Chrome and Apple have zero exclusive CAs. Mozilla has ${mozZero}. This asymmetry is structural: Chrome and Apple achieved their exclusive-CA count of zero by requiring cross-program review; Microsoft trusts CAs that no other program has evaluated.`;
          })()}
          This metric does not claim these CAs are misbehaving — only that the public record contains no evidence one way or the other.
        </MethodologyItem>
        <MethodologyItem label="Trust Store Changelogs">
          Chrome: complete history from Chromium source code git log (since 2022).
          Microsoft: monthly CTL deployment notices scraped from learn.microsoft.com (since 2020).
          Mozilla: Bugzilla inclusion and removal bugs with exact timestamps.
          Apple: no public changelog — daily CCADB snapshots build history over time from diffs.
        </MethodologyItem>
        <MethodologyItem label="Inclusion Gaps">
          Auto-detected: CAs with market share rank ≤ 100 or more than 100 unexpired certificates that are missing from at least one trust store.
          Wait time is approximated from root certificate creation date — CAs may not apply to all stores simultaneously so this is a lower bound.
          Mozilla pipeline stages use Bugzilla whiteboard labels which are not always applied consistently; stage labels should be treated as approximate.
        </MethodologyItem>
        <MethodologyItem label="Limitations and Bias">
          All metrics in this tab measure publicly observable behavior only. Root programs that govern through private channels (direct CA correspondence, private email threads, in-person meetings) will appear less active than programs that use Bugzilla and public mailing lists as their primary governance channel. Mozilla's high oversight count reflects their deliberate use of Bugzilla as a public governance record, not necessarily a higher absolute level of governance activity.
          Chrome's recent oversight engagement appears lower in absolute terms than Mozilla's all-time total, but Chrome's year-on-year growth since 2021 is the steepest of any program.
          Microsoft's 0% oversight reflects public Bugzilla data only. Their governance activity through private channels and CTL deployment decisions is not captured here.
          Apple's public Bugzilla participation has grown in recent years but remains modest relative to the corpus size; their governance posture is largely opaque due to limited public disclosure.
          The data here reflects what the ecosystem can observe externally — which is also what creates public accountability.
        </MethodologyItem>
        <MethodologyItem label="Data and Definitions">
          Unit of analysis: CA Owner (organization level). Certificate counts: unexpired precertificates from CT logs via crt.sh, grouped by Root Owner.
          Incident rate (Ops‡): cumulative Bugzilla bugs / all-time certs × 1,000,000 (lifetime rate, not annual).
          Usage period (†): 365 / (all-time certs / unexpired certs) — measures actual certificate replacement behavior, not configured validity period.
          Web coverage: trust store inclusion × StatCounter browser market share (Chrome ~{browserCoverage ? Math.round(browserCoverage.chrome * 100) : 78}%, Apple ~{browserCoverage ? Math.round(browserCoverage.apple * 100) : 16}%, Mozilla ~{browserCoverage ? Math.round(browserCoverage.mozilla * 100) : 2}%, Microsoft {'<'}1%). Values updated daily from StatCounter via pipeline.
          Pipeline runs daily at 06:00 UTC. Data freshness warnings: crt.sh/CCADB after 48h, critical after 7d.
          LLM comment classification uses claude-haiku. Classifications are cached and applied incrementally — new comments classified on each daily run. Unclassified comments default to governance=true.
        </MethodologyItem>
      </MethodologyCard>
    </div>
  );
};

export default GovernanceRiskView;
