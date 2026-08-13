import React, { useState, useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  AreaChart,
  Area,
  CartesianGrid,
  ScatterChart,
  Scatter,
  ZAxis,
  ReferenceLine,
  LabelList,
  PieChart,
  Pie,
} from 'recharts';
import { COLORS, ALPHA, FONT_MONO, FONT_SANS, COUNTRY_COORDS, INCIDENT_MILESTONES } from '../constants';
import { dn, f, fl } from '../helpers';
import {
  Card,
  CardTitle,
  StatCard,
  RateDot,
  ChartTooltip as TT,
  ChartWrap,
  GeoMap,
  DataPending,
  Paginator,
  TabIntro,
  MethodologyCard,
  MethodologyItem,
  CrlViewer,
} from './shared';
import CADetail from './CADetail';
import { usePipeline } from '../PipelineContext';
import {
  cardHeaderStyle, compactTableStyle, controlRowStyle, expandedCellStyle, footnoteStyle, narrowStatGrid, scrollXStyle, searchInputNarrow,
} from '../styles';

/**
 * OpsMap — Jurisdiction map for operational risk.
 * Aggregates incidents by CA country, supports absolute count
 * and per-million-certs normalized views.
 */
const OpsMap = ({ incidents }) => {
  const { caData } = usePipeline();
  const [mapMode, setMapMode] = useState('ppm');
  const pins = useMemo(() => {
    const byC = {};
    incidents.forEach((ca) => {
      const m = caData.find((x) => x.id === ca.id);
      const co = m?.country;
      if (!co || !COUNTRY_COORDS[co]) return;
      if (!byC[co]) byC[co] = { co, n: 0, v: 0, cas: [], ppm: [] };
      byC[co].n += ca.n;
      byC[co].cas.push(ca.ca);
      if (m) byC[co].v += m.certs;
      if (ca.ppm) byC[co].ppm.push(parseFloat(ca.ppm));
    });
    const entries = Object.values(byC).map((c) => ({
      ...c,
      avgPpm: c.ppm.length > 0 ? c.ppm.reduce((a, b) => a + b, 0) / c.ppm.length : null,
    }));
    if (mapMode === 'abs') {
      const mx = Math.max(...entries.map((c) => c.n), 1);
      return entries.map((c) => {
        const pct = c.n / mx;
        const cl = pct > 0.6 ? COLORS.rd : pct > 0.3 ? COLORS.am : COLORS.gn;
        return {
          lat: COUNTRY_COORDS[c.co].lat,
          lng: COUNTRY_COORDS[c.co].lng,
          label: c.co,
          color: cl,
          r: Math.max(4, Math.min(14, 3 + Math.sqrt(pct) * 11)),
          tooltip: (
            <div>
              <div style={{ fontWeight: 600, color: COLORS.tx }}>{c.co}</div>
              <div style={{ color: COLORS.t2 }}>
                {c.n} incidents · {c.cas.length} CAs
              </div>
              <div style={{ color: COLORS.t3, fontSize: 9 }}>{c.cas.join(', ')}</div>
            </div>
          ),
        };
      });
    } else {
      const withRate = entries.filter((c) => c.avgPpm !== null);
      const mx = Math.max(...withRate.map((c) => c.avgPpm), 0.01);
      return withRate.map((c) => {
        const pct = c.avgPpm / mx;
        const cl = pct > 0.6 ? COLORS.rd : pct > 0.3 ? COLORS.am : COLORS.gn;
        return {
          lat: COUNTRY_COORDS[c.co].lat,
          lng: COUNTRY_COORDS[c.co].lng,
          label: c.co,
          color: cl,
          r: Math.max(4, Math.min(14, 3 + Math.sqrt(pct) * 11)),
          tooltip: (
            <div>
              <div style={{ fontWeight: 600, color: COLORS.tx }}>{c.co}</div>
              <div style={{ color: COLORS.t2 }}>{c.avgPpm.toFixed(2)} per M certs</div>
              <div style={{ color: COLORS.t3, fontSize: 9 }}>
                {c.n} incidents · {f(c.certs)} certs
              </div>
            </div>
          ),
        };
      });
    }
  }, [incidents, mapMode]);
  return (
    <Card>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 8,
          marginBottom: 12,
        }}
      >
        <CardTitle
          sub={
            mapMode === 'abs'
              ? 'Dot size and color reflect total incident count. Red = highest concentration of incidents.'
              : 'Dot size and color reflect incidents per million certificates issued. Red = highest rate relative to issuance volume.'
          }
        >
          Operational Risk by Jurisdiction
        </CardTitle>
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          {[
            ['ppm', 'Per M Certs'],
            ['abs', 'Absolute'],
          ].map(([k, l]) => (
            <button
              key={k}
              onClick={() => setMapMode(k)}
              style={{
                padding: '4px 8px',
                fontSize: 9,
                borderRadius: 4,
                cursor: 'pointer',
                border: `1px solid ${mapMode === k ? COLORS.bl : COLORS.bd}`,
                background: mapMode === k ? COLORS.s2 : 'transparent',
                color: mapMode === k ? COLORS.t2 : COLORS.t3,
              }}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <GeoMap
        height={260}
        pins={pins}
        legend={[
          { color: COLORS.rd, label: 'High' },
          { color: COLORS.am, label: 'Medium' },
          { color: COLORS.gn, label: 'Low' },
        ]}
      />
    </Card>
  );
};

const toggleBtn = active => ({
  padding: '3px 10px', borderRadius: 4, border: `1px solid ${active ? COLORS.ac : COLORS.bd}`,
  background: active ? ALPHA.ac09 : 'transparent',
  color: active ? COLORS.ac : COLORS.t3, fontWeight: active ? 600 : 400,
  fontSize: 11, cursor: 'pointer',
});

/**
 * OpsView — Operational Risk tab.
 *
 * Visualizes CA incident data from Bugzilla CA Certificate Compliance.
 * Includes annual volume trends, AI-classified incident taxonomy
 * (misissuance, revocation, governance, validation), self-report rates,
 * and a detection capability scatter plot.
 */
const OpsView = () => {
  const { caData, incidentsData, rpeData } = usePipeline();

  if (!incidentsData || !incidentsData.total || !incidentsData.years || incidentsData.years.length === 0)
    return (
      <div>
        <DataPending
          tab="Operational Risk"
          source="Bugzilla CA Certificate Compliance"
          description="This tab visualizes CA operational risk derived from Mozilla's incident tracking dataset. The pipeline fetches bugs from Bugzilla, classifies incidents using AI, normalizes by issuance volume, and distinguishes self-reported from externally discovered issues. Data generation requires the pipeline to run with an Anthropic API key for classification."
        />
        <Card>
          <CardTitle>What This Tab Will Show</CardTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12, marginBottom: 12 }}>
            {[
              [
                'Annual Incident Volume',
                `The enforcement arc from ${firstBugYear} to present, showing how root program oversight evolved`,
              ],
              [
                `Top ${d.cas.length} CAs by Incident Count`,
                'Ranked by raw count, but with self-report % and per-million-certs normalization to provide fair context',
              ],
              [
                'Incident Classification',
                'AI-classified into categories: misissuance, CRL/OCSP, audit, policy violation, disclosure, key management',
              ],
              [
                'Self-Report vs External',
                'Distinguishes CAs that find their own problems from those whose issues are discovered by researchers or root programs',
              ],
              [
                'Ecosystem-Wide Incidents',
                'Identifies bugs that hit many CAs simultaneously (e.g. serial number entropy) and separates them from unique operational failures',
              ],
              [
                'Jurisdictional Map',
                'Geographic distribution of operational risk, with distrusted CA jurisdictions highlighted',
              ],
            ].map(([title, desc]) => (
              <div
                key={title}
                style={{
                  background: COLORS.bg,
                  borderRadius: 6,
                  padding: '10px 12px',
                  border: `1px solid ${COLORS.bd}`,
                }}
              >
                <div style={{ fontSize: 11, fontWeight: 600, color: COLORS.t2, marginBottom: 4 }}>{title}</div>
                <div style={{ fontSize: 9, color: COLORS.t3, lineHeight: 1.5 }}>{desc}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    );
  // When incidentsData is populated, render the full visualizations
  const d = incidentsData;
  const NOW = new Date();
  const CUR_YEAR = NOW.getFullYear();
  const CUR_MONTH_SHORT = NOW.toLocaleString('en-US', { month: 'short' });
  const PARTIAL_LABEL = `${CUR_YEAR} partial year (${CUR_MONTH_SHORT} YTD)`;
  const firstBugYear = d.years[0]?.y || 2014;
  const maxCA = d.cas[0]?.n || 1;
  const peakYear = d.years.reduce((a, b) => (b.n > a.n ? b : a), { n: 0 });
  const curYear = d.years[d.years.length - 1];
  const curPace = curYear ? Math.round(curYear.n * (365 / (new Date().getMonth() * 30.4 + new Date().getDate()))) : 0;
  const topCAsShare = Math.round((d.cas.reduce((s, c) => s + c.n, 0) / d.total) * 100);
  const avgSelf = d.cas.length > 0 ? Math.round(d.cas.reduce((s, c) => s + c.selfPct, 0) / d.cas.length) : 0;
  const withPpm = d.cas.map((ca) => {
    const m = caData.find((x) => x.id === ca.id);
    const allTime = m?.allTimeCerts || 0;
    // ctLow: fewer than 1000 CT-logged precerts — CA issues primarily outside CT.
    // The rate is computed but flagged so users know the denominator is unreliable
    // for cross-CA comparison. Suppression was rejected: the incident count is real
    // signal and hiding a high rate would conceal the reliability problem itself.
    const ctLow = allTime > 0 && allTime < 1000;
    return { ...ca,
      ppm: allTime > 0 ? ((ca.n / allTime) * 1e6).toFixed(2) : null,
      ctLow,
    };
  });
  const [opsCnt, setOpsCnt] = useState(10);
  const [opsExp, setOpsExp] = useState(null);
  const [srCnt, setSrCnt] = useState(10);
  const [fpCnt, setFpCnt] = useState(10);
  const [opsFilter, setOpsFilter] = useState('');
  // Milestone selection — these are editorial annotations, not pipeline data
  const [milestones, setMilestones] = useState(() => {
    const init = {};
    INCIDENT_MILESTONES.forEach((m) => { init[m.id] = m.measurement; });
    return init;
  });
  const toggleMilestone = (id) => setMilestones((p) => ({ ...p, [id]: !p[id] }));
  const setAllMilestones = (val) => {
    const o = {};
    INCIDENT_MILESTONES.forEach((m) => { o[m.id] = val; });
    setMilestones(o);
  };
  const resetMilestones = () => {
    const o = {};
    INCIDENT_MILESTONES.forEach((m) => { o[m.id] = m.measurement; });
    setMilestones(o);
  };
  const activeMilestones = INCIDENT_MILESTONES.filter((m) => milestones[m.id]);
  const opsFiltered = useMemo(() => {
    const q = opsFilter.toLowerCase();
    return q ? withPpm.filter((c) => c.ca.toLowerCase().includes(q)) : withPpm;
  }, [withPpm, opsFilter]);
  const opsShown = opsCnt === 0 ? opsFiltered : opsFiltered.slice(0, opsCnt);
  return (
    <div>
      <TabIntro tabId="ops" quote="By their incidents you shall know them.">
        Public compliance failures from Mozilla's Bugzilla CA Certificate Compliance tracker, normalized per million certificates issued to enable fair comparison across CAs of vastly different scale.
        Root programs discover more than half of all CA compliance incidents. CAs' own monitoring accounts for fewer than one in ten.
        The fastest-growing incident category is governance — audit failures, CPS violations, and disclosure failures — not certificate misissuance.
        Relying parties get an objective, data-driven reliability signal that marketing materials will never provide.
      </TabIntro>

      <div
        style={narrowStatGrid}
      >
        <StatCard l="Incidents" v={fl(d.total_with_distrusted || d.total)} s={`${d.ca_count_with_distrusted || d.ca_count} CAs · ${d.distrusted_excluded?.length || 0} distrusted`} c={COLORS.ac} />
        <StatCard l="Peak Year" v={peakYear.y} s={`${peakYear.n} incidents`} c={COLORS.am} />
        <StatCard
          l={`${curYear.y} YTD`}
          v={curYear.n}
          s={`~${curPace} annualized`}
          c={curPace > peakYear.n ? COLORS.rd : COLORS.t2}
        />
        <StatCard l={`Top ${d.cas.length} Share`} v={`${topCAsShare}%`} s="of all incidents" />
        {rpeData?.discovery_methods?.totals && (() => {
          const dm = rpeData.discovery_methods.totals;
          const grand = Object.values(dm).reduce((a, b) => a + b, 0);
          const selfPct = Math.round((dm.self_detected || 0) / grand * 100);
          const rpPct = Math.round((dm.root_program || 0) / grand * 100);
          const autoPct = Math.round((dm.community || 0) / grand * 100);
          return (
            <>
              <StatCard
                l="CA Self-Detection Rate"
                v={`${selfPct}%`}
                s={`of incidents found by CA's own monitoring — root programs find ${rpPct}%, automated tools find ${autoPct}%`}
                c={selfPct < 20 ? COLORS.am : COLORS.gn}
              />
            </>
          );
        })()}
        {(() => {
          const wb = d.whiteboardTags || {};
          const pf = wb['policy-failure'] || 0;
          const df = wb['disclosure-failure'] || 0;
          if (!pf && !df) return null;
          return (
            <StatCard
              l="Policy & Disclosure Failures"
              v={(pf + df).toLocaleString()}
              s={`incidents where CAs violated their own policies (${pf}) or failed timely disclosure (${df})`}
              c={COLORS.rd}
            />
          );
        })()}
        {(() => {
          const ybc = d.yearsByClass || [];
          const recent = ybc.filter(y => y.y >= 2019 && y.y < CUR_YEAR);
          const latest = recent[recent.length - 1];
          if (!latest) return null;
          const total = latest.mi + latest.rv + latest.gv + latest.vl;
          const govPct = total > 0 ? Math.round(latest.gv / total * 100) : 0;
          return (
            <StatCard
              l={`Governance Incidents ${latest.y}`}
              v={`${govPct}%`}
              s={`of all incidents — audit failures, CPS violations, disclosure`}
              c={govPct > 40 ? COLORS.rd : govPct > 25 ? COLORS.am : COLORS.t2}
            />
          );
        })()}
      </div>

      <Card>
        <CardTitle sub="Incidents filed under Bugzilla CA Certificate Compliance by year.">
          Annual Incident Volume
        </CardTitle>
        <ChartWrap height={220}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={d.years} margin={{ left: 4, right: 10, top: 10, bottom: 20 }}>
              <defs>
                <linearGradient id="og" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLORS.ac} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={COLORS.ac} stopOpacity={0.02} />
                </linearGradient>
              </defs>
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
              <YAxis tick={{ fill: COLORS.t3, fontSize: 9 }} axisLine={false} tickLine={false} width={28} />
              <Tooltip
                content={(p) => (
                  <TT
                    {...p}
                    render={(x) => (
                      <>
                        <div style={{ fontWeight: 600, color: COLORS.tx }}>
                          {x.y}
                          {x.y === 2026 ? ' (YTD)' : ''}
                        </div>
                        <div style={{ color: COLORS.t2 }}>{x.n} incidents</div>
                      </>
                    )}
                  />
                )}
              />
              <Area
                type="monotone"
                dataKey="n"
                stroke={COLORS.ac}
                strokeWidth={2}
                fill="url(#og)"
                dot={(props) => {
                  const { cx, cy, payload } = props;
                  const isCurrent = payload.y === new Date().getFullYear();
                  return isCurrent ? (
                    <circle cx={cx} cy={cy} r={4} fill="none" stroke={COLORS.am} strokeWidth={2} strokeDasharray="3 2" />
                  ) : (
                    <circle cx={cx} cy={cy} r={3} fill={COLORS.bg} stroke={COLORS.ac} strokeWidth={2} />
                  );
                }}
                activeDot={{ r: 5, fill: COLORS.ac }}
              />
              {activeMilestones.map((m) => (
                <ReferenceLine
                  key={m.id}
                  x={m.year}
                  stroke={m.color}
                  strokeDasharray="3 4"
                  strokeOpacity={0.7}
                  strokeWidth={1.5}
                  label={{
                    value: m.label,
                    position: 'insideTop',
                    angle: -90,
                    offset: -4,
                    style: {
                      fill: m.color,
                      fontSize: 8,
                      fontFamily: FONT_SANS,
                      fontWeight: 500,
                      textAnchor: 'start',
                    },
                  }}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </ChartWrap>
        <div style={{ fontSize: 9, color: COLORS.am, marginTop: 4 }}>
          ⚠ {d.years[d.years.length - 1]?.y} is year-to-date — dashed dot marks incomplete data. ~{curPace} incidents annualized at current pace.
        </div>
        {(d.total_with_distrusted && d.total_with_distrusted !== d.total) ? (
          <div style={{ fontSize: 9, color: COLORS.t3, marginTop: 2 }}>
            Chart shows {fl(d.total)} incidents from {d.ca_count} currently trusted CAs. {fl(d.total_with_distrusted - d.total)} additional from {d.distrusted_excluded?.length || 0} distrusted CAs
            ({(d.distrusted_excluded || []).filter(x => x.n > 0).slice(0, 5).map(x => `${x.ca}: ${x.n}`).join(', ')}{(d.distrusted_excluded || []).filter(x => x.n > 0).length > 5 ? ', …' : ''}) included in headline total.
          </div>
        ) : null}

        {/* Milestone strip */}
        <div style={{ marginTop: 12, borderTop: `1px solid ${COLORS.bd}`, paddingTop: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ fontSize: 9, fontWeight: 600, color: COLORS.t3, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Ecosystem Milestones
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {[
                ['All', () => setAllMilestones(true)],
                ['None', () => setAllMilestones(false)],
                ['Detection', resetMilestones],
              ].map(([label, fn]) => (
                <button
                  key={label}
                  onClick={fn}
                  style={{
                    padding: '2px 7px',
                    fontSize: 8,
                    borderRadius: 3,
                    cursor: 'pointer',
                    border: `1px solid ${COLORS.bd}`,
                    background: 'transparent',
                    color: COLORS.t3,
                    fontFamily: FONT_SANS,
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '1px 0' }}>
            {INCIDENT_MILESTONES.map((m) => {
              const on = milestones[m.id];
              return (
                <div
                  key={m.id}
                  onClick={() => toggleMilestone(m.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '4px 8px',
                    borderRadius: 4,
                    background: on ? COLORS.s2 : 'transparent',
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                >
                  <span
                    style={{
                      width: 12,
                      height: 12,
                      borderRadius: 2,
                      flexShrink: 0,
                      border: `1.5px solid ${on ? m.color : COLORS.bl}`,
                      background: on ? m.color + '22' : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 0,
                    }}
                  >
                    {on && (
                      <svg width="7" height="7" viewBox="0 0 10 10">
                        <polyline points="2,5 4.5,7.5 8,2.5" fill="none" stroke={m.color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </span>
                  <span style={{ fontFamily: FONT_MONO, fontSize: 9, fontWeight: 500, color: on ? COLORS.t2 : COLORS.t3, minWidth: 28 }}>
                    {m.year}
                  </span>
                  <span style={{ width: 5, height: 5, borderRadius: '50%', background: m.color, flexShrink: 0, opacity: on ? 1 : 0.3 }} />
                  <span style={{ color: on ? COLORS.tx : COLORS.t3, fontSize: 10, lineHeight: 1.3 }}>
                    {m.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </Card>

      {d.categories.length || d.yearsByClass.length || d.fingerprints.length ? (
        (() => {
          const CC = {
            mi: { l: 'Misissuance', c: '#e6a237' },
            rv: { l: 'Revocation', c: COLORS.rd },
            gv: { l: 'Governance', c: COLORS.gn },
            vl: { l: 'Validation', c: COLORS.pu },
          };
          const ybc = d.yearsByClass || [];
          const fp = d.fingerprints || [];
          return (
            <>
              {ybc.length > 0 && (
                <Card>
                  <CardTitle sub="Incident types by year — misissuance, revocation, governance (audit/policy failures), and validation. Current year is partial.">
                    Incidents by Class
                  </CardTitle>
                  <ChartWrap height={240}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={ybc} margin={{ left: 4, right: 10, top: 15, bottom: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.bd} />
                        <XAxis
                          dataKey="y"
                          type="number"
                          domain={['dataMin', 'dataMax']}
                          tick={({ x, y, payload }) => {
                            const isPartial = payload.value === CUR_YEAR;
                            return (
                              <text x={x} y={y + 12} fill={isPartial ? COLORS.am : COLORS.t3}
                                fontSize={9} textAnchor="middle">
                                {payload.value}{isPartial ? '*' : ''}
                              </text>
                            );
                          }}
                          axisLine={{ stroke: COLORS.bd }}
                          tickLine={false}
                          tickCount={7}
                        />
                        <YAxis tick={{ fill: COLORS.t3, fontSize: 9 }} axisLine={false} tickLine={false} width={28} />
                        <Tooltip
                          content={(p) => (
                            <TT
                              {...p}
                              render={(x) => (
                                <>
                                  <div style={{ fontWeight: 600, color: COLORS.tx }}>
                                    {x.y}{x.y === CUR_YEAR ? ' (partial)' : ''}
                                  </div>
                                  {[
                                    ['gv', 'Governance'],
                                    ['mi', 'Misissuance'],
                                    ['rv', 'Revocation'],
                                    ['vl', 'Validation'],
                                  ].map(
                                    ([k, l]) =>
                                      x[k] > 0 && (
                                        <div key={k} style={{ color: CC[k].c }}>
                                          {l}: {x[k]}
                                          
                                        </div>
                                      ),
                                  )}
                                  <div style={{ color: COLORS.t2, marginTop: 2 }}>
                                    Total: {(x.mi || 0) + (x.rv || 0) + (x.gv || 0) + (x.vl || 0)}
                                  </div>
                                </>
                              )}
                            />
                          )}
                        />
                        <Bar dataKey="mi" stackId="a" fill={CC.mi.c} opacity={0.8} radius={[0, 0, 0, 0]} />
                        <Bar dataKey="rv" stackId="a" fill={CC.rv.c} opacity={0.8} />
                        <Bar dataKey="gv" stackId="a" fill={CC.gv.c} opacity={0.8} />
                        <Bar dataKey="vl" stackId="a" fill={CC.vl.c} opacity={0.8} radius={[3, 3, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartWrap>
                  <div style={{ display: 'flex', gap: 14, fontSize: 9, color: COLORS.t3, marginTop: 4, flexWrap: 'wrap' }}>
                    {Object.entries(CC).map(([k, v]) => (
                      <span key={k}>
                        <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2,
                          background: v.c, opacity: 0.8, marginRight: 4, verticalAlign: 'middle' }} />
                        {v.l}
                      </span>
                    ))}
                    <span style={{ marginLeft: 'auto', color: COLORS.am }}>* {PARTIAL_LABEL}</span>
                  </div>
                  <div style={{ ...footnoteStyle, marginTop: 6 }}>
                    Governance = audit qualifications, CPS/policy violations, disclosure failures, CCADB non-compliance.
                    Governance incidents include audit qualifications, CPS/policy violations, and disclosure failures. Tags from Bugzilla whiteboard labels.
                  </div>
                </Card>
              )}

              {fp.length > 0 && (
                <Card>
                  <div
                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}
                  >
                    <CardTitle sub="Per-CA breakdown of incident types by classification.">
                      CA Incident Fingerprints
                    </CardTitle>
                    <Paginator count={fpCnt} setCount={setFpCnt} options={[10, 15, 25, 0]} />
                  </div>
                  {(fpCnt === 0 ? fp : fp.slice(0, fpCnt)).map((ca) => {
                    const tot = ca.mi + ca.rv + ca.gv + ca.vl;
                    return (
                      <div key={ca.ca} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span
                          title={ca.ca}
                          style={{
                            width: 130,
                            fontSize: 10,
                            color: COLORS.tx,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {ca.ca.length > 18 ? ca.ca.split(/[\s,]/)[0] : ca.ca}
                        </span>
                        <div style={{ flex: 1, height: 16, borderRadius: 3, overflow: 'hidden', display: 'flex' }}>
                          {[
                            ['mi', CC.mi.c],
                            ['rv', CC.rv.c],
                            ['gv', CC.gv.c],
                            ['vl', CC.vl.c],
                          ].map(
                            ([k, c]) => {
                              const pct = tot > 0 ? (ca[k] / tot) * 100 : 0;
                              return ca[k] > 0 && (
                                <div
                                  key={k}
                                  style={{
                                    width: `${pct}%`, background: c, opacity: 0.8,
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    overflow: 'hidden',
                                  }}
                                  title={`${CC[k].l}: ${ca[k]} (${pct.toFixed(0)}%)`}
                                >
                                  {pct >= 12 && (
                                    <span style={{ fontSize: 7, fontWeight: 600, color: COLORS.wh, textShadow: '0 0 2px rgba(0,0,0,0.5)' }}>
                                      {pct.toFixed(0)}%
                                    </span>
                                  )}
                                </div>
                              );
                            },
                          )}
                        </div>
                        <span
                          style={{
                            fontSize: 9,
                            color: COLORS.t3,
                            fontFamily: FONT_MONO,
                            width: 28,
                            textAlign: 'right',
                          }}
                        >
                          {tot}
                        </span>
                      </div>
                    );
                  })}
                  <div style={{ display: 'flex', gap: 14, fontSize: 9, color: COLORS.t3, marginTop: 8 }}>
                    {Object.entries(CC).map(([k, v]) => (
                      <span key={k}>
                        <span
                          style={{
                            display: 'inline-block',
                            width: 10,
                            height: 10,
                            borderRadius: 2,
                            background: v.c,
                            opacity: 0.8,
                            marginRight: 4,
                            verticalAlign: 'middle',
                          }}
                        />
                        {v.l}
                      </span>
                    ))}
                  </div>
                </Card>
              )}

              {!ybc.length && (
                <Card>
                  <CardTitle sub="Each incident classified by primary type: misissuance, revocation failure, governance/audit, or validation error. Classification sourced from Bugzilla whiteboard tags and bug summaries.">
                    Incident Classification
                  </CardTitle>
                  <div style={{ height: 32, borderRadius: 6, overflow: 'hidden', display: 'flex', marginBottom: 10 }}>
                    {d.categories.map((c) => {
                      const catColors = {
                        Misissuance: COLORS.rd,
                        'CRL / OCSP': COLORS.am,
                        Audit: COLORS.pu,
                        'Policy Violation': COLORS.pk,
                        'Revocation Delay': COLORS.or,
                        Disclosure: COLORS.cy,
                        Other: COLORS.t3,
                      };
                      const total = d.categories.reduce((s, x) => s + x.n, 0);
                      const w = (c.n / total) * 100;
                      return (
                        <div
                          key={c.cat}
                          style={{
                            width: `${w}%`,
                            background: catColors[c.cat] || COLORS.t3,
                            opacity: 0.7,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            borderRight: `1px solid ${COLORS.bg}`,
                          }}
                          title={`${c.cat}: ${c.n} (${w.toFixed(1)}%)`}
                        >
                          {w > 6 && (
                            <span style={{ fontSize: 8, color: COLORS.tx, fontWeight: 500 }}>{w.toFixed(0)}%</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 9, color: COLORS.t3 }}>
                    {d.categories.map((c) => (
                      <span key={c.cat}>
                        <span
                          style={{
                            display: 'inline-block',
                            width: 8,
                            height: 8,
                            borderRadius: 2,
                            background:
                              {
                                Misissuance: COLORS.rd,
                                'CRL / OCSP': COLORS.am,
                                Audit: COLORS.pu,
                                'Policy Violation': COLORS.pk,
                                'Revocation Delay': COLORS.or,
                                Disclosure: COLORS.cy,
                                Other: COLORS.t3,
                              }[c.cat] || COLORS.t3,
                            opacity: 0.7,
                            marginRight: 3,
                          }}
                        />
                        {c.cat} ({c.n})
                      </span>
                    ))}
                  </div>
                </Card>
              )}

              <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 2, lineHeight: 1.5 }}>
                Classification definitions: <strong style={{ color: COLORS.t2 }}>Misissuance</strong> = certificates
                issued violating the BRs (wrong SANs, encoding errors, serial number issues).{' '}
                <strong style={{ color: COLORS.t2 }}>Revocation</strong> = CRL/OCSP infrastructure failures and delayed
                revocation. <strong style={{ color: COLORS.t2 }}>Governance</strong> = audit qualifications, CPS
                violations, disclosure failures, CP/CPS non-compliance.{' '}
                <strong style={{ color: COLORS.t2 }}>Validation</strong> = domain/organization validation process
                failures.
              </div>
            </>
          );
        })()
      ) : (
        <DataPending
          tab="Incident Classification"
          source="Anthropic API (classification pipeline)"
          description="Incident taxonomy requires the classification pipeline to run. It categorizes each Bugzilla bug into Misissuance, Revocation, Governance, or Validation using AI analysis, then produces per-year and per-CA breakdowns. This enables the stacked bar chart showing how incident types evolve over time and per-CA fingerprints showing each CA's operational profile."
        />
      )}

      <Card>
        <div
          style={cardHeaderStyle}
        >
          <CardTitle sub="Incident count and incident rate per million certificates issued, per CA. Per-million rate normalizes for CA size. Only currently trusted CAs shown.">
            CAs by Incident Count
          </CardTitle>
          <div style={controlRowStyle}>
            <input
              value={opsFilter}
              onChange={(e) => setOpsFilter(e.target.value)}
              placeholder="Filter CAs..."
              style={searchInputNarrow}
            />
            <div style={{ display: 'flex', gap: 4 }}>
              {[10, 20, 0].map((n) => (
                <button
                  key={n}
                  onClick={() => setOpsCnt(n)}
                  style={{
                    padding: '4px 8px',
                    fontSize: 9,
                    borderRadius: 4,
                    cursor: 'pointer',
                    border: `1px solid ${opsCnt === n ? COLORS.bl : COLORS.bd}`,
                    background: opsCnt === n ? COLORS.s2 : 'transparent',
                    color: opsCnt === n ? COLORS.t2 : COLORS.t3,
                  }}
                >
                  {n === 0 ? 'All' : n}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div style={scrollXStyle}>
          <div style={{ overflowX: 'auto' }}>
          <table style={compactTableStyle}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.bd}` }}>
                {[
                  ['#', 'Rank by incident count'],
                  ['CA', 'CA organization (CCADB canonical name)'],
                  ['Incidents', 'Total Bugzilla CA Certificate Compliance bugs filed'],
                  ['Filed by CA', 'Percentage of incident bugs opened by CA staff (proxy for self-disclosure; does not indicate who discovered the issue)'],
                  ['Per M Certs', 'Incidents per million all-time certificates (normalizes for volume and time)'],
                  ['', 'Incident count bar'],
                ].map(([h, tip], i) => (
                  <th
                    key={i}
                    title={tip}
                    style={{
                      padding: '6px 5px',
                      color: COLORS.t3,
                      fontSize: 8,
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                      textAlign: i >= 2 ? 'right' : i === 5 ? 'left' : 'left',
                      cursor: tip ? 'help' : 'default',
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {opsShown.map((ca, i) => {
                const dEntry = caData.find((x) => x.id === ca.id);
                const isExp = opsExp === ca.ca;
                return (
                  <React.Fragment key={ca.ca}>
                    <tr
                      style={{ borderBottom: `1px solid ${COLORS.bd}`, cursor: dEntry ? 'pointer' : 'default' }}
                      onClick={() => dEntry && setOpsExp(isExp ? null : ca.ca)}
                    >
                      <td
                        style={{
                          padding: '5px',
                          textAlign: 'right',
                          color: COLORS.t3,
                          fontFamily: FONT_MONO,
                          fontSize: 9,
                        }}
                      >
                        {i + 1}
                      </td>
                      <td
                        title={ca.ca}
                        style={{
                          padding: '5px',
                          color: COLORS.tx,
                          maxWidth: 160,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {dEntry && (
                          <span style={{ fontSize: 9, color: isExp ? COLORS.ac : COLORS.t3, marginRight: 3 }}>
                            {isExp ? '▼' : '▶'}
                          </span>
                        )}
                        {dn(ca.ca)}
                      </td>
                      <td
                        style={{
                          padding: '5px',
                          textAlign: 'right',
                          fontFamily: FONT_MONO,
                          fontSize: 10,
                          color: COLORS.tx,
                        }}
                      >
                        {ca.n}
                      </td>
                      <td style={{ padding: '5px', textAlign: 'right', fontFamily: FONT_MONO, fontSize: 10 }}>
                        <span style={{ color: ca.selfPct > 60 ? COLORS.gn : ca.selfPct > 30 ? COLORS.t2 : COLORS.am }}>
                          {ca.selfPct}%
                        </span>
                      </td>
                      <td style={{ padding: '5px', textAlign: 'right', fontFamily: FONT_MONO, fontSize: 10 }}>
                        <span
                          style={{
                            color: ca.ppm && parseFloat(ca.ppm) > 1 ? COLORS.rd : ca.ppm ? COLORS.t2 : COLORS.t3,
                          }}
                        >
                          <RateDot ppm={ca.ppm ? parseFloat(ca.ppm) : 0} size={5} />{' '}
                          {ca.ppm || '—'}{ca.ctLow
                            ? <sup title="Rate based on fewer than 1,000 CT-logged precerts — this CA issues primarily outside Certificate Transparency. Incident count is accurate; per-million rate is not comparable across CAs." style={{ fontSize: 8, color: COLORS.am, marginLeft: 1 }}>†</sup>
                            : null}
                        </span>
                      </td>
                      <td style={{ padding: '5px', width: '30%' }}>
                        <div
                          style={{
                            position: 'relative',
                            height: 16,
                            background: COLORS.bg,
                            borderRadius: 3,
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              position: 'absolute',
                              height: '100%',
                              width: '100%',
                              background: COLORS.s1,
                              borderRadius: 3,
                            }}
                          />
                          <div
                            style={{
                              position: 'absolute',
                              height: '100%',
                              width: `${(ca.n / maxCA) * 100}%`,
                              background: COLORS.ac,
                              opacity: 0.6,
                              borderRadius: 3,
                            }}
                          />
                          <span
                            style={{
                              position: 'absolute',
                              right: 4,
                              top: 2,
                              fontSize: 8,
                              color: COLORS.tx,
                              fontFamily: FONT_MONO,
                            }}
                          >
                            {ca.n}
                          </span>
                        </div>
                      </td>
                    </tr>
                    {isExp && dEntry && (
                      <tr>
                        <td colSpan={6} style={expandedCellStyle}>
                          <CADetail d={dEntry} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          </div> {/* overflow wrapper */}
        </div>
        <div style={{ fontSize: 9, color: COLORS.t3, marginTop: 8, lineHeight: 1.5 }}>
          High incident count does not indicate low maturity. Volume CAs and transparent self-reporters accumulate more
          bugs. Self-Report: proportion filed by the CA itself (higher = more transparent). Per M Certs: incidents per
          million all-time precertificates (normalizes for volume).
          {' '}† Rate marked with † uses fewer than 1,000 CT-logged precerts as denominator — this CA issues primarily outside Certificate Transparency. The incident count is accurate; the per-million rate should not be used for cross-CA comparison.
          {d.distrusted_excluded &&
            d.distrusted_excluded.length > 0 &&
            ` Excluded ${d.distrusted_excluded.length} distrusted CAs (${d.distrusted_excluded.map((c) => c.caOwner).join(', ')}): no longer in any trust store.`}
        </div>
      </Card>

      {/* Operational risk jurisdiction map */}
      <OpsMap incidents={withPpm} />

      {/* Self-Report Rate */}
      {(() => {
        const allSorted = [...withPpm]
          .filter((ca) => ca.ca)
          .sort((a, b) => {
            const oa = incidentsData.cas.find((x) => x.id === a.id);
            const ob = incidentsData.cas.find((x) => x.id === b.id);
            return (ob?.selfPct || 0) - (oa?.selfPct || 0);
          })
          .map((ca) => {
            const o = incidentsData.cas.find((x) => x.id === ca.id);
            return {
              name: ca.ca.length > 18 ? ca.ca.split(/[\s,]/)[0] : ca.ca,
              full: ca.ca,
              selfPct: o?.selfPct || 0,
              selfN: o?.self || 0,
              extN: o?.ext || 0,
              n: o?.n || 0,
            };
          });
        const sorted = srCnt === 0 ? allSorted : allSorted.slice(0, srCnt);
        return (
          <Card>
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                gap: 8,
                marginBottom: 12,
              }}
            >
              <CardTitle sub="Proportion of incidents filed by the CA itself. High self-report rate suggests functional internal monitoring. Low rate suggests the CA only reports what external parties — researchers, root programs, automated tools — discover first.">
                Self-Report Rate
              </CardTitle>
              <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                {[10, 20, 0].map((n) => (
                  <button
                    key={n}
                    onClick={() => setSrCnt(n)}
                    style={{
                      padding: '4px 8px',
                      fontSize: 9,
                      borderRadius: 4,
                      cursor: 'pointer',
                      border: `1px solid ${srCnt === n ? COLORS.bl : COLORS.bd}`,
                      background: srCnt === n ? COLORS.s2 : 'transparent',
                      color: srCnt === n ? COLORS.t2 : COLORS.t3,
                    }}
                  >
                    {n === 0 ? 'All' : n}
                  </button>
                ))}
              </div>
            </div>
            <ChartWrap height={Math.max(200, sorted.length * 24)}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={sorted} layout="vertical" margin={{ left: 10, right: 16, top: 5, bottom: 5 }}>
                  <XAxis
                    type="number"
                    domain={[0, 100]}
                    tick={{ fill: COLORS.t3, fontSize: 9 }}
                    axisLine={{ stroke: COLORS.bd }}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fill: COLORS.t2, fontSize: 9, fontFamily: FONT_SANS }}
                    axisLine={false}
                    tickLine={false}
                    width={100}
                  />
                  <Tooltip
                    content={(p) => (
                      <TT
                        {...p}
                        render={(x) => (
                          <>
                            <div style={{ fontWeight: 600, color: COLORS.tx }}>{x.full}</div>
                            <div style={{ color: COLORS.t2 }}>
                              {x.selfPct}% filed by CA staff ({x.selfN} of {x.n})
                            </div>
                          </>
                        )}
                      />
                    )}
                  />
                  <ReferenceLine x={50} stroke={COLORS.bl} strokeDasharray="4 4" />
                  <Bar dataKey="selfPct" radius={[0, 4, 4, 0]} barSize={14}>
                    {sorted.map((d, i) => (
                      <Cell
                        key={i}
                        fill={d.selfPct > 60 ? COLORS.gn : d.selfPct > 30 ? COLORS.am : COLORS.rd}
                        fillOpacity={0.6}
                      />
                    ))}
                    <LabelList dataKey="selfPct" position="insideEnd" formatter={(v) => `${v}%`} style={{ fill: COLORS.wh, fontSize: 8, fontFamily: FONT_MONO }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartWrap>
            <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 4 }}>
              Dashed line = 50%. Green = strong (&gt;60%). Amber = moderate (30-60%). Red = weak (&lt;30%). Self-report
              attribution based on Bugzilla bug creator email domain matching.
            </div>
          </Card>
        );
      })()}

      {/* Detection Capability vs Incident Density scatter */}
      {(() => {
        const scatter = incidentsData.cas
          .map((ca) => {
            const m = caData.find((x) => x.id === ca.id);
            if (!m) return null;
            const allTime = m.allTimeCerts || 0;
            if (!allTime) return null;
            const ppm = (ca.n / allTime) * 1e6;
            const ctLow = allTime < 1000;
            return {
              name: ca.ca.length > 20 ? ca.ca.split(/[\s,]/)[0] : ca.ca,
              full: ca.ca,
              x: ca.selfPct,
              y: ppm,
              z: Math.max(40, Math.min(400, Math.sqrt(m.certs / 1e4))),
              n: ca.n,
              certs: allTime,
              ctLow,
            };
          })
          .filter(Boolean);
        return (
          <Card>
            <CardTitle sub="X-axis: self-report rate. Y-axis: incidents per million certs (log scale).">
              Detection Capability vs Incident Density
            </CardTitle>
            <ChartWrap height={320}>
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ left: 8, right: 20, top: 10, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.bd} />
                  <XAxis
                    type="number"
                    dataKey="x"
                    domain={[0, 100]}
                    tick={{ fill: COLORS.t3, fontSize: 9 }}
                    axisLine={{ stroke: COLORS.bd }}
                    tickLine={false}
                    label={{
                      value: 'Self-Report Rate %',
                      position: 'insideBottom',
                      offset: -8,
                      fill: COLORS.t3,
                      fontSize: 9,
                    }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    scale="log"
                    domain={['auto', 'auto']}
                    tick={{ fill: COLORS.t3, fontSize: 9 }}
                    axisLine={false}
                    tickLine={false}
                    width={38}
                  />
                  <ZAxis type="number" dataKey="z" range={[40, 400]} />
                  <ReferenceLine x={50} stroke={COLORS.bl} strokeDasharray="5 5" />
                  <Tooltip
                    content={(p) => (
                      <TT
                        {...p}
                        render={(x) => (
                          <>
                            <div style={{ fontWeight: 600, color: COLORS.tx }}>{x.full}</div>
                            <div style={{ color: COLORS.t2 }}>Self-report: {x.x}%</div>
                            <div style={{ color: COLORS.t2 }}>
                              {x.n} incidents · {f(x.certs)} certs
                            </div>
                            <div style={{ color: x.ctLow ? COLORS.am : COLORS.t2 }}>
                              {x.y.toFixed(2)} per M certs{x.ctLow ? ' †' : ''}
                            </div>
                            {x.ctLow && (
                              <div style={{ fontSize: 9, color: COLORS.am, marginTop: 2 }}>
                                † &lt;1,000 CT precerts — rate unreliable
                              </div>
                            )}
                          </>
                        )}
                      />
                    )}
                  />
                  <Scatter data={scatter}>
                    {scatter.map((d, i) => (
                      <Cell key={i} fill={d.x < 30 ? COLORS.rd : d.x < 60 ? COLORS.am : COLORS.gn} fillOpacity={0.7} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </ChartWrap>
            <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 4 }}>
              Dot color: <span style={{ color: COLORS.gn }}>●</span> &gt;60% self-report{' '}
              <span style={{ color: COLORS.am }}>●</span> 30-60% <span style={{ color: COLORS.rd }}>●</span> &lt;30%.
              Dot size reflects issuance volume. All data from Bugzilla CA Certificate Compliance + crt.sh.
            </div>
          </Card>
        );
      })()}

      {/* ── Discovery Method Trend ── */}
      {rpeData?.discovery_methods?.by_year?.length > 0 && (() => {
        const dm = rpeData.discovery_methods;
        const byYear = dm.by_year.filter(y => y.y >= 2017 && y.total > 0);
        const totals = dm.totals || {};
        const grand = Object.values(totals).reduce((a, b) => a + b, 0);
        const METHODS = [
          { key: 'root_program',        label: 'Root Program',       color: COLORS.ac },
          { key: 'audit',               label: 'Audit',              color: COLORS.gn },
          { key: 'external_researcher', label: 'External Researcher',color: COLORS.pu },
          { key: 'community',           label: 'Automated Tools (CT/Linting)', color: COLORS.cy },
          { key: 'self_detected',       label: 'CA Self-Detected',    color: COLORS.am },
          { key: 'unknown',             label: 'Unknown',            color: COLORS.t3 },
        ];
        // Compute pct version for stacked area
        const pctData = byYear.map(y => {
          const row = { y: y.y };
          METHODS.forEach(m => { row[m.key] = y.total > 0 ? Math.round(y[m.key] / y.total * 100) : 0; });
          return row;
        });
        return (
          <Card>
            <CardTitle sub="Who discovers CA compliance problems? Root program share has been declining as audit detection and external research grow. Current year is partial.">
              Incident Discovery Method Trends
            </CardTitle>
            <div style={{ display: 'flex', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
              {METHODS.filter(m => (totals[m.key] || 0) > 0).map(m => (
                <span key={m.key} style={{ fontSize: 9, color: COLORS.t3, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: m.color, opacity: 0.8 }} />
                  {m.label} ({Math.round((totals[m.key] || 0) / grand * 100)}%)
                </span>
              ))}
            </div>
            <ChartWrap height={220}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={pctData} margin={{ left: 4, right: 16, top: 8, bottom: 20 }} stackOffset="expand">
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.bd} />
                  <XAxis
                    dataKey="y"
                    type="number"
                    domain={['dataMin', 'dataMax']}
                    tick={({ x, y, payload }) => (
                      <text x={x} y={y + 12} fill={payload.value === 2026 ? COLORS.am : COLORS.t3}
                        fontSize={9} textAnchor="middle">
                        {payload.value}{payload.value === 2026 ? '*' : ''}
                      </text>
                    )}
                    axisLine={{ stroke: COLORS.bd }} tickLine={false}
                  />
                  <YAxis
                    tickFormatter={v => `${Math.round(v * 100)}%`}
                    tick={{ fill: COLORS.t3, fontSize: 9 }}
                    axisLine={false} tickLine={false}
                    width={32}
                  />
                  <Tooltip
                    contentStyle={{ background: COLORS.s2, border: `1px solid ${COLORS.bd}`, borderRadius: 6, fontSize: 11 }}
                    labelStyle={{ color: COLORS.tx, fontWeight: 600, marginBottom: 4 }}
                    formatter={(val, name) => {
                      const m = METHODS.find(m => m.key === name);
                      return [`${Math.round(val * 100)}%`, m?.label || name];
                    }}
                    labelFormatter={y => `${y}${y === CUR_YEAR ? ' (partial)' : ''}`}
                  />
                  {METHODS.map(m => (
                    <Area key={m.key} type="monotone" dataKey={m.key}
                      stackId="1" fill={m.color} stroke={m.color}
                      fillOpacity={0.75} strokeWidth={0} />
                  ))}
                  {activeMilestones
                    .filter(m => m.year >= 2017)
                    .map(m => (
                      <ReferenceLine key={m.id} x={m.year}
                        stroke={m.color} strokeDasharray="3 4"
                        strokeOpacity={0.8} strokeWidth={1.5}
                        label={{
                          value: m.label,
                          position: 'insideTop',
                          offset: 4,
                          style: { fill: m.color, fontSize: 7, fontFamily: FONT_SANS, fontWeight: 500 },
                        }}
                      />
                    ))}
                </AreaChart>
              </ResponsiveContainer>
            </ChartWrap>
            <div style={{ ...footnoteStyle, marginTop: 6 }}>
              {(() => {
                const first = byYear[0];
                const last = byYear[byYear.length - 2]; // exclude partial current year
                const rpFirst = first?.total > 0 ? Math.round(first.root_program / first.total * 100) : 0;
                const rpLast  = last?.total  > 0 ? Math.round(last.root_program  / last.total  * 100) : 0;
                const auLast  = last?.total  > 0 ? Math.round(last.audit         / last.total  * 100) : 0;
                return `Root program detection: ${rpFirst}% (${first?.y}) → ${rpLast}% (${last?.y}). Audit-detected: ${auLast}% (${last?.y}).`;
              })()}
              {' '}* {PARTIAL_LABEL}.
            </div>
          </Card>
        );
      })()}

      <CrlHealthView />

      <div style={{ fontSize: 9, color: COLORS.t3, textAlign: 'right',
                    padding: '6px 4px 12px', marginTop: 4 }}>
        Incident data: Bugzilla CA Certificate Compliance · {d.total} bugs · {d.ca_count} CAs · Updated {rpeData?.meta?.generated_at?.slice(0, 10) || 'daily'}
      </div>

      <MethodologyCard>
        <MethodologyItem label="Incident rate (Ops‡)">{`Cumulative Bugzilla CA Certificate Compliance bugs (${firstBugYear}–present) divided by all-time certificates issued, per million. Lifetime rate, not annual. Uses all-time denominator to match the all-time numerator.`}</MethodologyItem>
        <MethodologyItem label="Classification">Incident tags (misissuance, revocation delay, etc.) from Bugzilla whiteboard labels and LLM classification of bug summaries. Some bugs may have incomplete or missing tags.</MethodologyItem>
        <MethodologyItem label="Incident limitation">Only captures publicly-filed Bugzilla incidents. CAs not yet in any trust store rarely file incidents. Higher incident counts may indicate better self-reporting, not worse operations.</MethodologyItem>
        <MethodologyItem label="CRL health — fetch">Every CRL URL filed in CCADB for trusted active CA certificates is probed daily. TLS verification is intentionally skipped per RFC 5280 §6.3: CRL distribution is unauthenticated by design, and root CA CRL servers legitimately secure their endpoints with their own PKI rather than a public CA. The CRL signature is the integrity check, not the transport. URLs with no scheme are inferred as http:// and flagged as a CCADB data quality issue.</MethodologyItem>
        <MethodologyItem label="CRL health — TLS">For HTTPS-filed URLs, the TLS certificate presented by the server is inspected. Hostname mismatch and expired certs are flagged as genuine errors regardless of who issued the cert. For HTTP-filed URLs, port 443 on the same host is probed to check whether an HTTPS endpoint exists and whether its TLS cert is healthy. A revoked TLS cert on the HTTPS endpoint is cross-checked against revoked serials from CRLs fetched in the same run.</MethodologyItem>
        <MethodologyItem label="CRL health — issuer match">The CRL issuer DN is compared against the CCADB cert subject DN. A mismatch means the wrong CRL URL is filed in CCADB. Certificates issued by that CA are not affected if they carry their own CDP extensions pointing to the correct CRL — browsers fetching CDPs directly from the certificate will get the right revocation data. However, CRLite (Firefox) and CRL Sets (Chrome) are built by aggregating CRLs from CCADB records; an incorrect CCADB URL means those aggregated offline revocation databases may be missing revocations from that CA.</MethodologyItem>
        <MethodologyItem label="CRL health — BR §4.9.7">CRL validity window (nextUpdate − thisUpdate) is assessed against CA/Browser Forum Baseline Requirements §4.9.7. CRLs covering subordinate CA certificates must have nextUpdate no more than 12 months after thisUpdate. CRLs with more than 100 revoked entries are assumed to cover end-entity subscriber certificates, for which the limit is 10 days. BR compliance is only assessed for CAs included in Apple, Chrome, or Mozilla trust stores — Microsoft-only government CAs are typically not TLS-issuing and are not governed by CA/B Forum BRs; their applicable standard is national PKI policy.</MethodologyItem>
        <MethodologyItem label="CRL health — store dots">Coloured dots on each CA row indicate trust store presence: grey = Apple, green = Chrome, orange = Mozilla, blue = Microsoft. CAs with only a blue dot are Microsoft-only and likely government PKIs.</MethodologyItem>
      </MethodologyCard>
    </div>
  );
};

// ── CRL Infrastructure Health ──────────────────────────────────────────────────

// Returns a tooltip string explaining a URL's status in detail
function _statusDetail(u) {
  switch (u.status) {
    case 'ok':                    return u.next_update_iso ? `Valid until ${u.next_update_iso.slice(0,10)}` : 'CRL is valid and current';
    case 'url_inferred':          return `CCADB filed this URL without an http:// or https:// scheme. We inferred http:// and the CRL fetched successfully, but the CA should correct the CCADB record.`;
    case 'br_violation':          return `CRL validity window is ${u.validity_window_days}d, exceeding the BR §4.9.7 limit of ${u.br_validity_limit_days}d${(u.revoked_count||0)>100?' (end-entity scope — >100 revoked)':' (sub-CA scope)'}.`;
    case 'https_cert_revoked':    return `HTTPS endpoint at port 443 exists but its TLS certificate serial appears in a CRL fetched this run — the server's own cert has been revoked.`;
    case 'https_cert_expired':    return `HTTPS endpoint at port 443 exists but its TLS certificate is expired.`;
    case 'https_hostname_mismatch': return `HTTPS endpoint at port 443 exists but the TLS cert doesn't cover hostname ${new URL(u.fetch_url||u.url).hostname}.`;
    case 'issuer_mismatch':       return `Wrong CRL URL in CCADB. CRL is signed by ${u.issuer?.slice(0,80)} but CCADB cert is ${u.issuer_match_detail}. CDP-fetching browsers are unaffected; CRLite/CRL Sets may miss revocations.`;
    case 'stale':                 return `CRL has expired — nextUpdate was ${u.next_update_iso||'unknown'}. The CA has not refreshed their CRL.`;
    case 'parse_failed':          return `Server returned a response but it is not a valid CRL${u.error === 'url_is_index' ? ' — URL appears to be a directory listing page' : u.error === 'html_response' ? ' — server returned an HTML page' : ''}.`;
    case 'tls_hostname_mismatch': return `TLS certificate on ${new URL(u.fetch_url||u.url).hostname} does not cover this hostname. The URL may be wrong or the server is misconfigured.`;
    case 'tls_cert_expired':      return `TLS certificate on this HTTPS CRL server is expired.`;
    case 'invalid_url':           return `URL cannot be fetched — ${(u.url_errors||[]).join(', ') || 'missing scheme or hostname'}.`;
    case 'connection_error':      return u.error || 'Server is unreachable from the public internet.';
    case 'dns_error':             return `Hostname does not resolve: ${u.error||''}`;
    case 'timeout':               return `Connection timed out after ${u.elapsed_ms}ms.`;
    default:
      if (u.status?.startsWith('http_')) return `HTTP ${u.status.slice(5)} — ${u.error||''}`;
      return u.error || u.status;
  }
}

const MIN_HISTORY_SAMPLES = 3; // hide over-time view until this many daily snapshots exist

// Unified status taxonomy — every condition maps to exactly one status.
// Drives labels, colors, filter chips, worstOf, and parent badges.
const STATUS_META = {
  ok:                       { color: COLORS.gn, label: 'OK' },
  // Data quality
  url_inferred:             { color: COLORS.am, label: 'No protocol in URL' },
  // BR compliance
  br_violation:             { color: COLORS.am, label: 'BR §4.9.7 violation' },
  // HTTPS endpoint issues (HTTP-filed URLs)
  https_hostname_mismatch:  { color: COLORS.am, label: 'HTTPS hostname mismatch' },
  https_cert_expired:       { color: COLORS.am, label: 'HTTPS cert expired' },
  https_cert_revoked:       { color: COLORS.rd, label: 'HTTPS cert revoked' },
  // CRL content
  issuer_mismatch:          { color: COLORS.rd, label: 'Wrong CRL filed' },
  stale:                    { color: COLORS.am, label: 'Stale CRL' },
  parse_failed:             { color: COLORS.am, label: 'Not a CRL' },
  // TLS failures (HTTPS-filed URLs)
  tls_hostname_mismatch:    { color: COLORS.rd, label: 'TLS hostname mismatch' },
  tls_cert_expired:         { color: COLORS.rd, label: 'TLS cert expired' },
  // HTTP errors
  http_404:                 { color: COLORS.rd, label: '404 Not Found' },
  http_403:                 { color: COLORS.am, label: '403 Forbidden' },
  http_500:                 { color: COLORS.am, label: '500 Server Error' },
  http_503:                 { color: COLORS.am, label: '503 Unavailable' },
  // Fetch failures
  connection_error:         { color: COLORS.am, label: 'Unreachable' },
  timeout:                  { color: COLORS.am, label: 'Timeout' },
  dns_error:                { color: COLORS.am, label: 'DNS failure' },
  invalid_url:              { color: COLORS.rd, label: 'Invalid URL' },
  unknown:                  { color: COLORS.t3, label: 'Unknown' },
};

function statusMeta(status) {
  if (!status) return { color: COLORS.t3, label: '—' };
  if (STATUS_META[status]) return STATUS_META[status];
  if (status.startsWith('http_')) return { color: COLORS.am, label: `HTTP ${status.slice(5)}` };
  if (status.startsWith('tls_')) return { color: COLORS.rd, label: `TLS: ${status.slice(4).replace(/_/g,' ')}` };
  return { color: COLORS.t3, label: status };
}


function CrlHealthView() {
  const { crlHealthData, crlHealthHistory, crlHealthEvents } = usePipeline();
  const [_subView, _setSubView] = useState(null);  // null = auto
  const [sortCol, setSortCol] = useState('status');
  const [sortAsc, setSortAsc] = useState(false);
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterShared, setFilterShared] = useState(false);
  const [storeSort, setStoreSort] = useState(null); // null | 'apple'|'chrome'|'mozilla'|'microsoft'
  const [colSort, setColSort] = useState(null);     // null | {col, dir:'asc'|'desc'}
  const [expandedCrl, setExpandedCrl] = useState(null);

  const urls     = useMemo(() => crlHealthData?.urls     ?? [], [crlHealthData]);
  const summary  = useMemo(() => crlHealthData?.summary  ?? {}, [crlHealthData]);
  const events   = useMemo(() => Array.isArray(crlHealthEvents) ? crlHealthEvents : [], [crlHealthEvents]);
  const history  = useMemo(() => crlHealthHistory ?? {}, [crlHealthHistory]);

  // How many distinct daily samples do we have across all URLs?
  const historySampleCount = useMemo(() => {
    const dates = new Set();
    Object.values(history).forEach(arr => arr.forEach(e => e.date && dates.add(e.date)));
    return dates.size;
  }, [history]);

  const hasEnoughHistory = historySampleCount >= MIN_HISTORY_SAMPLES;
  // Default to 'history' once data is available, 'snapshot' otherwise
  const subView = _subView ?? (hasEnoughHistory ? 'history' : 'snapshot');
  const setSubView = _setSubView;

  // Build grouped CA rows for hierarchical table
  const STATUS_PRIORITY = [
    'invalid_url', 'dns_error', 'connection_error', 'timeout',
    'http_404', 'http_500', 'http_503', 'http_403',
    'tls_hostname_mismatch', 'tls_cert_expired',
    'parse_failed', 'stale', 'issuer_mismatch',
    'https_cert_revoked', 'https_cert_expired', 'https_hostname_mismatch',
    'br_violation', 'url_inferred', 'ok',
  ];

  const worstOf = (statuses, inferredFlags) => {
    let best = 'ok';
    for (const s of statuses) {
      const pi = STATUS_PRIORITY.indexOf(s);
      const bi = STATUS_PRIORITY.indexOf(best);
      if (pi !== -1 && (bi === -1 || pi < bi)) best = s;
    }
    // If all ok but some inferred, signal data quality issue at CA level
    if (best === 'ok' && inferredFlags?.some(Boolean)) return 'inferred';
    return best;
  };

  const caGroups = useMemo(() => {
    const byCA = {};
    urls.forEach(u => {
      const ca = u.ca_owner || 'Unknown';
      if (!byCA[ca]) byCA[ca] = {
        ca, urls: [], totalRevoked: 0,
        minExpiry: null, medianElapsed: null,
      };
      byCA[ca].urls.push(u);
      if (u.url_inferred) byCA[ca].hasInferred = true;
      if (u.revoked_count != null) byCA[ca].totalRevoked += u.revoked_count;
      if (u.hours_until_expiry != null) {
        if (byCA[ca].minExpiry === null || u.hours_until_expiry < byCA[ca].minExpiry)
          byCA[ca].minExpiry = u.hours_until_expiry;
      }
    });

    return Object.values(byCA).map(g => {
      const elapsed = g.urls.map(u => u.elapsed_ms).filter(v => v != null).sort((a,b)=>a-b);
      const mid = Math.floor(elapsed.length / 2);
      g.medianElapsed = elapsed.length ? elapsed[mid] : null;
      g.worstStatus = worstOf(g.urls.map(u => u.status));
      g.okCount = g.urls.filter(u => u.status === 'ok').length;
      return g;
    }).sort((a, b) => {
      // Issues first, then alphabetical
      const ai = STATUS_PRIORITY.indexOf(a.worstStatus);
      const bi = STATUS_PRIORITY.indexOf(b.worstStatus);
      if (ai !== bi) return ai - bi;
      return a.ca.localeCompare(b.ca);
    });
  }, [urls]);

  // Build history chart data — availability % per day across all URLs
  const historyChartData = useMemo(() => {
    if (!hasEnoughHistory) return [];
    const byDate = {};
    Object.values(history).forEach(arr => {
      arr.forEach(e => {
        if (!e.date) return;
        if (!byDate[e.date]) byDate[e.date] = { date: e.date, ok: 0, total: 0, stale: 0, mismatch: 0 };
        byDate[e.date].total++;
        if (e.fetch_ok && e.parse_ok && !e.is_stale && e.issuer_match !== false)
          byDate[e.date].ok++;
        if (e.is_stale) byDate[e.date].stale++;
        if (e.issuer_match === false) byDate[e.date].mismatch++;
      });
    });
    return Object.values(byDate)
      .sort((a, b) => a.date.localeCompare(b.date))
      .map(d => ({ ...d, pct: d.total > 0 ? Math.round(d.ok / d.total * 100) : null }));
  }, [history, hasEnoughHistory]);

  // Filter caGroups by status
  const filteredGroups = useMemo(() => {
    const pred = filterStatus === 'all'    ? () => true
               : filterStatus === 'issues' ? u => u.status !== 'ok'
               :                             u => u.status === filterStatus;
    const sharedPred = filterShared ? u => u.shared_with_cas?.length > 0 : () => true;
    let groups = caGroups
      .map(g => ({ ...g, urls: g.urls.filter(u => pred(u) && sharedPred(u)) }))
      .filter(g => g.urls.length > 0);
    // When a store is selected, CAs in that store sort first (preserving
    // worst-status ordering within each group), others sort after.
    if (storeSort) {
      const storeKey = `in_${storeSort}`;
      groups = [
        ...groups.filter(g => g.urls[0]?.[storeKey]),
        ...groups.filter(g => !g.urls[0]?.[storeKey]),
      ];
    }
    // Column sort (takes precedence over default status-first order)
    if (colSort) {
      groups = [...groups].sort((a, b) => {
        let av, bv;
        if (colSort.col === 'ca')      { av = a.ca;            bv = b.ca; }
        else if (colSort.col === 'urls')    { av = a.urls.length;  bv = b.urls.length; }
        else if (colSort.col === 'ms')     { av = a.medianElapsed ?? -1; bv = b.medianElapsed ?? -1; }
        else if (colSort.col === 'revoked'){ av = a.totalRevoked ?? -1; bv = b.totalRevoked ?? -1; }
        else if (colSort.col === 'expiry') { av = a.minExpiry ?? 999999; bv = b.minExpiry ?? 999999; }
        else if (colSort.col === 'status') { av = STATUS_PRIORITY.indexOf(a.worstStatus); bv = STATUS_PRIORITY.indexOf(b.worstStatus); }
        if (av === bv) return a.ca.localeCompare(b.ca);
        const cmp = av < bv ? -1 : 1;
        return colSort.dir === 'asc' ? cmp : -cmp;
      });
    }
    return groups;
  }, [caGroups, filterStatus, filterShared, storeSort, colSort]);

  if (!crlHealthData) {
    return (
      <Card>
        <CardTitle>CRL Infrastructure Health</CardTitle>
        <div style={{ color: COLORS.t3, fontSize: 12, padding: '16px 0' }}>
          CRL health data not yet available — runs daily via CI pipeline.
        </div>
      </Card>
    );
  }

  // Status filter options from actual data
  const statusCounts = useMemo(() => {
    const counts = {};
    urls.forEach(u => { counts[u.status] = (counts[u.status] || 0) + 1; });
    return counts;
  }, [urls]);

  return (
    <Card>
      {/* Header */}
      <div style={{ ...cardHeaderStyle, justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <CardTitle sub={`${summary.total_urls ?? 0} CRL URLs · ${summary.ca_count ?? 0} CAs · probed ${crlHealthData.generated_at?.slice(0,10) ?? '—'}`}>
            CRL Infrastructure Health
          </CardTitle>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {hasEnoughHistory
            ? <button style={toggleBtn(subView === 'history')} onClick={() => setSubView('history')}>Over Time</button>
            : <button style={{ ...toggleBtn(false), opacity: 0.4, cursor: 'default' }}
                title={`Over time view available after ${MIN_HISTORY_SAMPLES} daily samples (${historySampleCount} so far)`}>
                Over Time ({historySampleCount}/{MIN_HISTORY_SAMPLES})
              </button>
          }
          <button style={toggleBtn(subView === 'snapshot')} onClick={() => setSubView('snapshot')}>Snapshot</button>
          {events.length > 0 &&
            <button style={toggleBtn(subView === 'events')} onClick={() => setSubView('events')}>Changes</button>
          }
        </div>
      </div>

      {/* KPI chips */}
      <div style={{ display: 'flex', gap: 10, padding: '10px 16px', flexWrap: 'wrap', borderBottom: `1px solid ${COLORS.bd}` }}>
        {[
          { label: 'OK',            v: summary.ok_count,                                       c: COLORS.gn },
          { label: 'URL Issues',    v: summary.issue_count ?? summary.fail_count,
                                     c: (summary.issue_count ?? summary.fail_count) > 0 ? COLORS.rd : COLORS.t3,
                                     title: 'URLs with any non-ok status' },
          { label: 'CAs w/ Issues', v: summary.cas_with_issues,
                                     c: summary.cas_with_issues > 0 ? COLORS.am : COLORS.t3,
                                     title: 'Distinct CAs with at least one issue' },
          { label: 'Changes today', v: summary.changes_today ?? events.length,
                                     c: (summary.changes_today ?? 0) > 0 ? COLORS.am : COLORS.t3,
                                     title: 'State changes detected in this run (CRL refreshes, outages, recovered)' },
          { label: 'Total revoked', v: summary.total_revoked?.toLocaleString(),
                                     c: COLORS.t2,
                                     title: 'Sum of all revoked certificate entries across all parsed CRLs' },
          { label: 'Global rev. rate',
            v: summary.global_revocation_ppm != null
               ? `${summary.global_revocation_ppm.toFixed(2)} ppm`
               : '—',
            c: COLORS.t2,
            title: 'Revoked certs ÷ unexpired certs (from crt.sh market share data). Aggregated across CAs with both datasets available. Most meaningful globally — individual CA rates are only reliable when the CRL covers end-entity certs.' },
          { label: 'Rev / day',
            v: summary.revocations_per_day != null
               ? summary.revocations_per_day.toFixed(1)
               : '—',
            c: COLORS.t2,
            title: 'Total revoked cert entries ÷ sum of CRL validity windows. Estimates the ecosystem-wide revocation rate in certificates per day.' },
          { label: 'No caching headers',
            v: summary.cache_no_cc ?? '—',
            c: (summary.cache_no_cc ?? 0) > 0 ? COLORS.am : COLORS.t3,
            title: 'RFC 5019 §6.1: CRL servers SHOULD set Cache-Control max-age equal to the CRL validity period. Without it, proxies and CDNs apply their own heuristics and may serve stale revocation data.' },
          { label: 'Cache > CRL validity',
            v: summary.cache_exceeds_count ?? '—',
            c: (summary.cache_exceeds_count ?? 0) > 0 ? COLORS.rd : COLORS.t3,
            title: 'Cache-Control max-age or Expires exceeds the CRL validity window. Intermediaries may cache and serve stale revocation data past nextUpdate.' },
        ].map(({ label, v, c, title }) => (
          <div key={label} title={title}
            style={{ padding: '6px 10px', borderRadius: 6, background: COLORS.s2,
            border: `1px solid ${COLORS.bd}`, minWidth: 80, cursor: title ? 'help' : 'default' }}>
            <div style={{ fontSize: 18, fontWeight: 500, color: c }}>{v ?? '—'}</div>
            <div style={{ fontSize: 10, color: COLORS.t3, marginTop: 1 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* ── Overview charts ── */}
      {(() => {
        const statusCts = summary.status_counts || {};
        const okCount   = statusCts.ok || 0;
        const totalUrls = summary.total_urls || 0;
        const issueCount = totalUrls - okCount;

        // Health donut data
        const healthData = [
          { name: 'Healthy', value: okCount,    color: COLORS.gn },
          { name: 'Issues',  value: issueCount, color: COLORS.rd },
        ];

        // Issue breakdown (excluding ok)
        const issueEntries = Object.entries(statusCts)
          .filter(([s]) => s !== 'ok')
          .sort((a, b) => b[1] - a[1]);
        const ISSUE_COLORS = [COLORS.rd, COLORS.am, COLORS.am, COLORS.am, COLORS.am, COLORS.t3];

        // Revocation reasons
        const reasonEntries = Object.entries(summary.revocation_reasons || {})
          .sort((a, b) => b[1] - a[1]);
        const REASON_COLORS = [COLORS.t3, COLORS.ac, COLORS.gn, COLORS.pu, COLORS.rd, COLORS.am, COLORS.cy];

        // Issues by store
        const urls_ = urls;
        const storeCounts = { Apple: 0, Chrome: 0, Mozilla: 0, 'MSFT only': 0 };
        urls_.filter(u => u.status !== 'ok').forEach(u => {
          const a = u.in_apple, c = u.in_chrome, m = u.in_mozilla, w = u.in_microsoft;
          if (w && !a && !c && !m) storeCounts['MSFT only']++;
          else {
            if (a) storeCounts['Apple']++;
            if (c) storeCounts['Chrome']++;
            if (m) storeCounts['Mozilla']++;
          }
        });
        const storeData = Object.entries(storeCounts)
          .filter(([,n]) => n > 0)
          .map(([name, value], i) => ({
            name, value,
            color: name === 'MSFT only' ? '#0078D4' : name === 'Apple' ? '#999' : name === 'Chrome' ? '#4CAF50' : '#FF6611'
          }));

        if (totalUrls === 0) return null;

        const miniLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, name, value }) => {
          if (value === 0) return null;
          const RADIAN = Math.PI / 180;
          const r = innerRadius + (outerRadius - innerRadius) * 0.5;
          const x = cx + r * Math.cos(-midAngle * RADIAN);
          const y = cy + r * Math.sin(-midAngle * RADIAN);
          return value / (summary.total_urls || 1) > 0.05
            ? <text x={x} y={y} fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={9} fontWeight={600}>{value}</text>
            : null;
        };

        return (
          <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))',
                        gap: 0, borderBottom: `1px solid ${COLORS.bd}` }}>

            {/* 1. Health donut */}
            <div style={{ padding: '12px 8px 8px', borderRight: `1px solid ${COLORS.bd}`, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: COLORS.t3, marginBottom: 4 }}>CRL Health</div>
              <div style={{ position: 'relative', height: 90 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={healthData} cx="50%" cy="50%" innerRadius={28} outerRadius={42}
                         dataKey="value" strokeWidth={0} labelLine={false} label={miniLabel}>
                      {healthData.map((d, i) => <Cell key={i} fill={d.color} />)}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: COLORS.s2, border: `1px solid ${COLORS.bd}`, fontSize: 10 }}
                      formatter={(v, name) => [`${v} URLs`, name]} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ position: 'absolute', top: '50%', left: '50%',
                              transform: 'translate(-50%,-50%)', textAlign: 'center', pointerEvents: 'none' }}>
                  <div style={{ fontSize: 14, fontWeight: 700,
                                color: issueCount === 0 ? COLORS.gn : COLORS.rd }}>
                    {okCount > 0 ? `${Math.round(okCount/totalUrls*100)}%` : '—'}
                  </div>
                  <div style={{ fontSize: 8, color: COLORS.t3 }}>healthy</div>
                </div>
              </div>
              <div style={{ fontSize: 9, color: COLORS.t3 }}>{okCount} of {totalUrls} URLs ok</div>
              <div className="crl-description" style={{ fontSize: 8, color: COLORS.t3, marginTop: 3, lineHeight: 1.4, padding: '0 4px' }}>
                Each CA files a CRL URL in CCADB. We probe every one daily and check the CRL is fetchable, parseable, current, and signed by the right CA.
              </div>
            </div>

            {/* 2. CRL expiry headroom */}
            {(() => {
              const expiryBuckets = [
                { label: 'Expired',  color: COLORS.rd,  count: 0, hrs: [-Infinity, 0] },
                { label: '< 7d',     color: COLORS.rd,  count: 0, hrs: [0,    168] },
                { label: '7–30d',    color: COLORS.am,  count: 0, hrs: [168,  720] },
                { label: '30–90d',   color: COLORS.t2,  count: 0, hrs: [720,  2160] },
                { label: '90d+',     color: COLORS.gn,  count: 0, hrs: [2160, Infinity] },
              ];
              urls.forEach(u => {
                const h = u.hours_until_expiry;
                if (h == null) return;
                const b = expiryBuckets.find(b => h >= b.hrs[0] && h < b.hrs[1]);
                if (b) b.count++;
              });
              const maxCount = Math.max(...expiryBuckets.map(b => b.count), 1);
              return (
                <div style={{ padding: '12px 10px 8px', borderRight: `1px solid ${COLORS.bd}` }}>
                  <div style={{ fontSize: 10, color: COLORS.t3, marginBottom: 8, textAlign: 'center' }}>CRL Expiry Headroom</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '0 2px' }}>
                    {expiryBuckets.map(b => (
                      <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 9, color: COLORS.t3, width: 36, textAlign: 'right',
                                       flexShrink: 0 }}>{b.label}</span>
                        <div style={{ flex: 1, height: 10, borderRadius: 3,
                                      background: COLORS.bd, overflow: 'hidden' }}>
                          {b.count > 0 && (
                            <div style={{ width: `${Math.round(b.count / maxCount * 100)}%`,
                                          height: '100%', background: b.color,
                                          borderRadius: 3, minWidth: 4 }} />
                          )}
                        </div>
                        <span style={{ fontSize: 9, fontWeight: b.color === COLORS.rd && b.count > 0 ? 600 : 400,
                                       color: b.count > 0 ? b.color : COLORS.t3,
                                       width: 22, textAlign: 'right', flexShrink: 0 }}>{b.count}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 6, lineHeight: 1.4 }}>
                    Time until each CRL must be refreshed (nextUpdate). Red = expired or expiring within a week. A growing red count would signal CAs failing to refresh on schedule.
                  </div>
                </div>
              );
            })()}

            {/* 3. Issues by trust store — dot list */}
            <div style={{ padding: '12px 10px 8px', borderRight: `1px solid ${COLORS.bd}` }}>
              <div style={{ fontSize: 10, color: COLORS.t3, marginBottom: 8, textAlign: 'center' }}>Issues by Trust Store</div>
              {storeData.length === 0
                ? <div style={{ fontSize: 10, color: COLORS.gn, textAlign: 'center', paddingTop: 20 }}>✓ No issues</div>
                : <div style={{ display: 'flex', flexDirection: 'column', gap: 5, padding: '4px 4px' }}>
                    {[
                      { key: 'MSFT only', color: '#0078D4', label: 'Microsoft only' },
                      { key: 'Mozilla',   color: '#FF6611', label: 'Mozilla' },
                      { key: 'Apple',     color: '#999',    label: 'Apple' },
                      { key: 'Chrome',    color: '#4CAF50', label: 'Chrome' },
                    ].map(({ key, color, label }) => {
                      const d = storeData.find(s => s.name === key);
                      const n = d?.value || 0;
                      return (
                        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%',
                                         background: color, opacity: n > 0 ? 1 : 0.2,
                                         flexShrink: 0 }} />
                          <span style={{ fontSize: 9, color: n > 0 ? color : COLORS.t3,
                                         flex: 1 }}>{label}</span>
                          <span style={{ fontSize: 10, fontWeight: n > 0 ? 600 : 400,
                                         color: n > 0 ? color : COLORS.t3 }}>{n}</span>
                        </div>
                      );
                    })}
                  </div>
              }
              {storeData.length > 0 && (
                <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 8, padding: '0 4px',
                              lineHeight: 1.4 }}>
                  Microsoft-only CAs are typically government PKIs not governed by CA/B Forum BRs.
                </div>
              )}
            </div>

            {/* 4. Revocation reasons donut */}
            <div style={{ padding: '12px 8px 8px', textAlign: 'center', borderRight: `1px solid ${COLORS.bd}` }}>
              <div style={{ fontSize: 10, color: COLORS.t3, marginBottom: 4 }}>Revocation Reasons</div>
              {reasonEntries.length === 0
                ? <div style={{ fontSize: 10, color: COLORS.t3, textAlign: 'center', paddingTop: 24 }}>No data</div>
                : <>
                    <div style={{ position: 'relative', height: 90 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie data={reasonEntries.map(([name,value]) => ({name,value}))}
                               cx="50%" cy="50%" innerRadius={22} outerRadius={42}
                               dataKey="value" strokeWidth={0} labelLine={false}>
                            {reasonEntries.map(([,], i) => <Cell key={i} fill={REASON_COLORS[i % REASON_COLORS.length]} />)}
                          </Pie>
                          <Tooltip
                            contentStyle={{ background: COLORS.s2, border: `1px solid ${COLORS.bd}`, fontSize: 10 }}
                            formatter={(v, name) => [`${v.toLocaleString()} (${Math.round(v/(summary.total_revoked||1)*100)}%)`, name]} />
                        </PieChart>
                      </ResponsiveContainer>
                      <div style={{ position: 'absolute', top: '50%', left: '50%',
                                    transform: 'translate(-50%,-50%)', textAlign: 'center', pointerEvents: 'none' }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: COLORS.tx }}>
                          {(summary.total_revoked||0).toLocaleString()}
                        </div>
                        <div style={{ fontSize: 7, color: COLORS.t3 }}>revoked</div>
                      </div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1, marginTop: 2 }}>
                      {reasonEntries.slice(0,4).map(([name, n], i) => (
                        <div key={name} style={{ display: 'flex', justifyContent: 'space-between',
                                                  fontSize: 8, padding: '0 4px' }}>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                            <span style={{ width: 6, height: 6, borderRadius: 1,
                                           background: REASON_COLORS[i % REASON_COLORS.length],
                                           display: 'inline-block', flexShrink: 0 }} />
                            <span style={{ color: COLORS.t2 }}>{name}</span>
                          </span>
                          <span style={{ color: COLORS.t3 }}>{Math.round(n/(summary.total_revoked||1)*100)}%</span>
                        </div>
                      ))}
                    </div>
                  </>
              }
            </div>

            {/* 5. CRL Infrastructure Sharing */}
            {(() => {
              const sh = crlHealthData?.shared_crl_summary;
              if (!sh) return null;
              const crossCount  = sh.cross_ca_shared_urls   ?? 0;
              const withinCount = sh.within_ca_shared_urls  ?? 0;
              const casSharing  = sh.cas_with_cross_shared  ?? 0;
              const topDomains  = (sh.top_hosting_domains   ?? []).slice(0, 6);
              const total       = sh.total_urls ?? 1;
              const maxDomain   = Math.max(...topDomains.map(d => d.url_count), 1);
              return (
                <div style={{ padding: '12px 10px 8px' }}>
                  <div style={{ fontSize: 10, color: COLORS.t3, marginBottom: 8, textAlign: 'center' }}>
                    CRL Infrastructure Sharing
                  </div>
                  {/* Cross-CA / within-CA counts */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9 }}>
                      <span style={{ color: COLORS.t3 }}
                        title="CRL URLs referenced by 2+ distinct CA organizations in CCADB — indicates outsourced or shared revocation infrastructure">
                        Cross-CA shared
                      </span>
                      <span style={{ color: crossCount > 0 ? COLORS.am : COLORS.t3, fontWeight: crossCount > 0 ? 600 : 400 }}>
                        {crossCount.toLocaleString()} <span style={{ color: COLORS.t3, fontWeight: 400 }}>
                          ({Math.round(crossCount / total * 100)}%)
                        </span>
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9 }}>
                      <span style={{ color: COLORS.t3 }}
                        title="CRL URLs shared across multiple intermediates of the same CA organization">
                        Within-CA shared
                      </span>
                      <span style={{ color: COLORS.t2 }}>{withinCount.toLocaleString()}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9 }}>
                      <span style={{ color: COLORS.t3 }}
                        title="Number of CA organizations whose CRL infrastructure is shared with at least one other CA">
                        CAs w/ cross-sharing
                      </span>
                      <span style={{ color: COLORS.t2 }}>{casSharing}</span>
                    </div>
                  </div>
                  {/* Top hosting domains */}
                  <div style={{ fontSize: 9, color: COLORS.t3, marginBottom: 4 }}>Top CRL hosting domains</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {topDomains.map(d => (
                      <div key={d.domain} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        <span style={{ fontSize: 8, color: COLORS.t3, width: 80,
                                       overflow: 'hidden', textOverflow: 'ellipsis',
                                       whiteSpace: 'nowrap', flexShrink: 0,
                                       fontFamily: FONT_MONO }}
                          title={d.domain}>{d.domain}</span>
                        <div style={{ flex: 1, height: 8, borderRadius: 2,
                                      background: COLORS.bd, overflow: 'hidden' }}>
                          <div style={{ width: `${Math.round(d.url_count / maxDomain * 100)}%`,
                                        height: '100%', background: COLORS.ac,
                                        borderRadius: 2, minWidth: 3, opacity: 0.7 }} />
                        </div>
                        <span style={{ fontSize: 8, color: COLORS.t3, width: 30,
                                       textAlign: 'right', flexShrink: 0 }}>
                          {d.url_count.toLocaleString()}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 6, lineHeight: 1.4 }}>
                    Cross-CA shared CRLs signal outsourced revocation infrastructure — one CA hosting revocation data for another. This creates operational dependency and single-point-of-failure risk.
                  </div>
                </div>
              );
            })()}
          </div>
          <div style={{ fontSize: 8, color: COLORS.t3, marginTop: 6, lineHeight: 1.5 }}>
            Each CA files a CRL URL in CCADB. We probe daily: fetch reachability, CRL parse validity, issuer DN match, and BR §4.9.7 validity window.
            Red expiry = CRL must be refreshed within a week. A growing red count signals CAs failing to refresh on schedule.
          </div>
          </>
        );
      })()}

      {/* ── SNAPSHOT VIEW — grouped by CA ── */}
      {subView === 'snapshot' && (() => {
        const expiryLabel = h => h == null ? '—' : h < 0 ? 'Expired' : h < 24 ? `${Math.round(h)}h` : `${Math.round(h/24)}d`;
        const expiryColor = h => h == null ? COLORS.t3 : h < 0 ? COLORS.rd : h < 24 ? COLORS.rd : h < 168 ? COLORS.am : COLORS.t2;
        const onColSort = col => setColSort(prev =>
          prev?.col === col
            ? prev.dir === 'asc' ? { col, dir: 'desc' } : null  // cycle: asc→desc→off
            : { col, dir: 'asc' });
        const sortIcon = col => {
          if (colSort?.col !== col) return <span style={{ opacity: 0.25, marginLeft: 3 }}>⇅</span>;
          return <span style={{ marginLeft: 3, color: COLORS.ac }}>{colSort.dir === 'asc' ? '↑' : '↓'}</span>;
        };
        const thSort = col => ({
          ...th, cursor: 'pointer', userSelect: 'none',
          color: colSort?.col === col ? COLORS.ac : COLORS.t3,
        });
        const th = { padding: '5px 10px', fontSize: 10, color: COLORS.t3,
                     borderBottom: `1px solid ${COLORS.bd}`, whiteSpace: 'nowrap', textAlign: 'right' };
        const thL = { ...th, textAlign: 'left' };
        return (
          <div>
            {/* Store sort selector */}
            {(() => {
              const stores = [
                { key: 'apple',     color: '#999',    label: 'Apple' },
                { key: 'chrome',    color: '#4CAF50', label: 'Chrome' },
                { key: 'mozilla',   color: '#FF6611', label: 'Mozilla' },
                { key: 'microsoft', color: '#0078D4', label: 'Microsoft' },
              ];
              const activeStore = stores.find(s => s.key === storeSort);
              return (
                <div style={{ ...controlRowStyle, padding: '4px 16px 0', gap: 8,
                              justifyContent: 'flex-end', alignItems: 'center' }}>
                  {/* Dynamic label — shows current sort state clearly */}
                  {activeStore
                    ? <span style={{ fontSize: 10, color: activeStore.color, fontWeight: 600 }}>
                        <span style={{ width: 7, height: 7, borderRadius: '50%',
                                       background: activeStore.color, display: 'inline-block',
                                       marginRight: 4, verticalAlign: 'middle' }} />
                        Sorted by {activeStore.label}
                      </span>
                    : <span style={{ fontSize: 10, color: COLORS.t3 }}>Sort by store:</span>
                  }
                  {stores.map(({ key, color, label }) => {
                    const active = storeSort === key;
                    return (
                      <button key={key}
                        onClick={() => setStoreSort(active ? null : key)}
                        title={active ? `Clear — currently sorted by ${label}` : `Sort ${label} CAs to top`}
                        style={{
                          ...toggleBtn(active),
                          ...(active ? {
                            border: `1px solid ${color}`,
                            background: color + '22',
                            color,
                          } : {}),
                          display: 'flex', alignItems: 'center', gap: 4,
                        }}>
                        <span style={{ width: 7, height: 7, borderRadius: '50%',
                                       background: color, display: 'inline-block',
                                       opacity: active ? 1 : 0.6, flexShrink: 0 }} />
                        {label}
                      </button>
                    );
                  })}
                  {storeSort &&
                    <button onClick={() => setStoreSort(null)}
                      style={{ ...toggleBtn(false), padding: '3px 6px' }}
                      title="Clear store sort">✕</button>}
                </div>
              );
            })()}
            {(() => {
              const issueCount = urls.filter(u => u.status !== 'ok').length;
              const nonOkStatuses = Object.entries(statusCounts)
                .filter(([s]) => s !== 'ok')
                .sort((a, b) => b[1] - a[1]);
              return (
                <div style={{ padding: '8px 16px 6px', display: 'flex',
                              flexDirection: 'column', gap: 4 }}>
                  {/* Single row: All | All Issues | [sub-filters inline] */}
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button style={toggleBtn(filterStatus === 'all')}
                      onClick={() => setFilterStatus('all')}>
                      All ({urls.length})
                    </button>
                    {issueCount > 0 && (<>
                      <button style={toggleBtn(filterStatus === 'issues')}
                        onClick={() => setFilterStatus('issues')}>
                        All Issues ({issueCount})
                      </button>
                      {nonOkStatuses.map(([s, n]) => (
                        <button key={s} style={{
                          ...toggleBtn(filterStatus === s),
                          borderColor: filterStatus === s ? statusMeta(s).color : COLORS.bd,
                          color: filterStatus === s ? statusMeta(s).color : COLORS.t3,
                          fontSize: 10,
                        }}
                          onClick={() => setFilterStatus(filterStatus === s ? 'issues' : s)}>
                          {statusMeta(s).label} ({n})
                        </button>
                      ))}
                    </>)}
                    {(() => {
                      const crossCount = urls.filter(u => u.shared_with_cas?.length > 0).length;
                      if (crossCount === 0) return null;
                      return (
                        <button style={{
                          ...toggleBtn(filterShared),
                          ...(filterShared ? {
                            borderColor: COLORS.am,
                            background: COLORS.am + '22',
                            color: COLORS.am,
                          } : {}),
                          fontSize: 10,
                        }}
                          onClick={() => setFilterShared(f => !f)}
                          title="Show only URLs whose CRL infrastructure is shared with another CA organization">
                          Cross-CA Shared ({crossCount})
                        </button>
                      );
                    })()}
                  </div>
                </div>
              );
            })()}

            <div style={scrollXStyle}>
              <table style={{ ...compactTableStyle, width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: COLORS.s2 }}>
                    <th style={{ ...thL, paddingLeft: 14, cursor:'pointer', userSelect:'none' }}
                        onClick={() => onColSort('ca')}>CA / URL {sortIcon('ca')}</th>
                    <th style={th} title="Trust store presence">Stores</th>
                    <th style={thSort('status')} onClick={() => onColSort('status')}>Status {sortIcon('status')}</th>
                    <th style={thSort('urls')} onClick={() => onColSort('urls')} title="Number of CRL URLs filed for this CA">CRLs {sortIcon('urls')}</th>
                    <th style={thSort('ms')} onClick={() => onColSort('ms')}>Median ms {sortIcon('ms')}</th>
                    <th style={thSort('revoked')} onClick={() => onColSort('revoked')}>Total revoked {sortIcon('revoked')}</th>
                    <th style={thSort('expiry')} onClick={() => onColSort('expiry')}>Soonest expiry {sortIcon('expiry')}</th>
                    <th style={th} title="CRL validity window (nextUpdate − thisUpdate) vs BR §4.9.7 limit">CRL window</th>
                    <th style={th} title="HTTP caching headers vs CRL validity window (RFC 5019 §6.1)">Cache-Control</th>
                    <th style={th}></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredGroups.map((g, gi) => {
                    const wsm = statusMeta(g.worstStatus);
                    const allOk = g.worstStatus === 'ok';
                    return (
                      <React.Fragment key={gi}>
                        {/* CA parent row */}
                        <tr style={{ background: (() => {
                                       if (allOk) return 'transparent';
                                       const p = STATUS_PRIORITY.indexOf(g.worstStatus);
                                       const total = STATUS_PRIORITY.length;
                                       // Severity: 0=worst (invalid_url) → total-1=best (ok)
                                       // Map to opacity: severe=20%, moderate=12%, mild=6%
                                       const severity = 1 - (p / total);
                                       const opacity = Math.round(severity * 20 + 4);
                                       return wsm.color + opacity.toString(16).padStart(2,'0');
                                     })(),
                                     borderTop: gi > 0 ? `1px solid ${COLORS.bd}` : 'none' }}>
                          <td style={{ padding: '6px 10px 6px 14px', fontSize: 12,
                                       fontWeight: 500, color: COLORS.tx,
                                       borderBottom: `1px solid ${COLORS.bd}` }}>
                            {g.ca}
                          </td>
                          {/* Store dots column */}
                          <td style={{ padding: '6px 8px', textAlign: 'center',
                                       borderBottom: `1px solid ${COLORS.bd}`, whiteSpace: 'nowrap' }}>
                            {(() => {
                              const u0 = g.urls[0];
                              if (!u0) return null;
                              return [
                                { key: 'in_apple',     color: '#999',    label: 'Apple' },
                                { key: 'in_chrome',    color: '#4CAF50', label: 'Chrome' },
                                { key: 'in_mozilla',   color: '#FF6611', label: 'Mozilla' },
                                { key: 'in_microsoft', color: '#0078D4', label: 'Microsoft' },
                              ].map(({ key, color, label }) => (
                                <span key={key} title={u0[key] ? label : `Not in ${label}`}
                                  style={{ display: 'inline-block', width: 7, height: 7,
                                    borderRadius: '50%', marginLeft: 2,
                                    background: u0[key] ? color : COLORS.bd,
                                    opacity: u0[key] ? 0.9 : 0.3,
                                    verticalAlign: 'middle' }} />
                              ));
                            })()}
                          </td>
                          <td style={{ padding: '6px 10px', textAlign: 'right',
                                       borderBottom: `1px solid ${COLORS.bd}` }}>
                            {allOk
                              ? <span style={{ fontSize: 10, color: COLORS.gn }}>✓ all ok</span>
                              : (() => {
                                  const issueCount = g.urls.length - g.okCount;
                                  return <span style={{ fontSize: 10, fontWeight: 600, color: wsm.color }}>
                                    {issueCount} issue{issueCount !== 1 ? 's' : ''}
                                  </span>;
                                })()
                            }
                          </td>
                          <td style={{ padding: '6px 10px', fontSize: 11, textAlign: 'right',
                                       color: COLORS.t2, borderBottom: `1px solid ${COLORS.bd}` }}
                            title={`${g.okCount} of ${g.urls.length} URLs healthy`}>
                            {g.urls.length}
                          </td>
                          <td style={{ padding: '6px 10px', fontSize: 11, textAlign: 'right',
                                       color: g.medianElapsed > 3000 ? COLORS.am : COLORS.t2,
                                       borderBottom: `1px solid ${COLORS.bd}` }}>
                            {g.medianElapsed != null ? `${g.medianElapsed}` : '—'}
                          </td>
                          <td style={{ padding: '6px 10px', fontSize: 11, textAlign: 'right',
                                       color: COLORS.t2, borderBottom: `1px solid ${COLORS.bd}` }}>
                            {g.totalRevoked > 0 ? g.totalRevoked.toLocaleString() : '—'}
                          </td>
                          <td style={{ padding: '6px 10px', fontSize: 11, textAlign: 'right',
                                       color: expiryColor(g.minExpiry),
                                       fontWeight: g.minExpiry != null && g.minExpiry < 168 ? 600 : 400,
                                       borderBottom: `1px solid ${COLORS.bd}` }}>
                            {expiryLabel(g.minExpiry)}
                          </td>
                          <td style={{ padding: '6px 10px', fontSize: 11, textAlign: 'right',
                                       borderBottom: `1px solid ${COLORS.bd}` }}>
                            {(() => {
                              const hasWindow = g.urls.some(u => u.validity_window_days != null);
                              if (!hasWindow) return <span style={{ color: COLORS.t3 }}>—</span>;
                              const governed = g.urls.some(u => u.br_governed);
                              if (!governed) return <span style={{ color: COLORS.t3, fontSize: 10 }} title="Not CA/B Forum BR-governed — national PKI policy applies">n/a</span>;
                              const violations = g.urls.filter(u => u.status === 'br_violation');
                              if (violations.length > 0)
                                return <span style={{ color: statusMeta('br_violation').color, fontWeight: 600 }}>⚠ {violations.length} violation{violations.length>1?'s':''}</span>;
                              return <span style={{ color: COLORS.gn }}>✓</span>;
                            })()}
                          </td>
                          <td style={{ padding: '6px 10px', fontSize: 10, textAlign: 'right',
                                       borderBottom: `1px solid ${COLORS.bd}` }}>
                            {(() => {
                              const fetched = g.urls.filter(u => u.fetch_ok);
                              const exc = g.urls.filter(u => u.cache_exceeds_window === true).length;
                              const ncc = fetched.filter(u => u.cache_control == null).length;
                              if (exc > 0)
                                return <span style={{ color: COLORS.rd, fontSize: 10 }}
                                  title="Cache max-age exceeds CRL validity window">⚠ exceeds window</span>;
                              if (ncc === fetched.length && ncc > 0)
                                return <span style={{ color: COLORS.am, fontSize: 10 }}
                                  title={`All ${ncc} CRL URLs missing caching headers (RFC 5019 §6.1)`}>no caching headers</span>;
                              if (ncc > 0)
                                return <span style={{ color: COLORS.am, fontSize: 10 }}
                                  title={`${ncc} of ${fetched.length} CRL URLs missing caching headers`}>{ncc} missing</span>;
                              const withCC = fetched.filter(u => u.cache_control != null).length;
                              return withCC > 0
                                ? <span style={{ color: COLORS.t3, fontSize: 10 }}>{withCC}/{fetched.length}</span>
                                : <span style={{ color: COLORS.t3 }}>—</span>;
                            })()}
                          </td>
                          <td style={{ borderBottom: `1px solid ${COLORS.bd}` }} />
                        </tr>

                        {/* URL child rows */}
                        {g.urls.map((u, ui) => {
                          const sm = statusMeta(u.status);
                          const isLast = ui === g.urls.length - 1;
                          return (
                            <React.Fragment key={ui}>
                            <tr style={{ background: ALPHA.s220 }}>
                              <td style={{ padding: '4px 10px 4px 28px', fontSize: 10,
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33`,
                                           maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis',
                                           whiteSpace: 'nowrap', color: COLORS.t3 }}>
                                <span style={{ marginRight: 4, color: COLORS.bd }}>└</span>
                                <a href={u.fetch_url || u.url} target="_blank" rel="noopener noreferrer"
                                  style={{ color: u.url_inferred ? COLORS.am
                                           : u.status === 'ok' ? COLORS.t3 : sm.color,
                                           textDecoration: 'none', fontFamily: FONT_MONO }}
                                  onMouseOver={e => e.target.style.color = COLORS.ac}
                                  onMouseOut={e => e.target.style.color = u.url_inferred ? COLORS.am
                                              : u.status === 'ok' ? COLORS.t3 : sm.color}
                                  title={u.url_inferred
                                    ? `Stored in CCADB as: ${u.url}\nFetched as: ${u.fetch_url}\n(http:// scheme was inferred — CCADB data quality issue)`
                                    : u.url}>
                                  {(u.fetch_url || u.url)?.replace(/^https?:\/\//, '').slice(0, 60)}
                                  {(u.fetch_url || u.url)?.length > 66 ? '…' : ''}
                                </a>
                                {u.url_inferred &&
                                  <span style={{ marginLeft: 4, fontSize: 9, color: COLORS.am,
                                    fontWeight: 600 }} title="http:// scheme was inferred — CCADB stores this URL without a scheme prefix">
                                    ⚠ inferred scheme
                                  </span>}
                                {(u.url_info ?? u.url_issues)?.filter(x => x !== 'inferred_http_scheme').length > 0 &&
                                  <span style={{ marginLeft: 5, fontSize: 9, color: COLORS.t3,
                                    opacity: 0.7 }}>
                                    [{(u.url_info ?? u.url_issues).filter(x => x !== 'inferred_http_scheme').join(', ')}]
                                  </span>}
                                {/* CRL source badge */}
                                {u.crl_source === 'partitioned' && (
                                  <span style={{ marginLeft: 5, fontSize: 8, padding: '1px 4px',
                                    borderRadius: 3, background: COLORS.ac + '22',
                                    color: COLORS.ac, fontWeight: 600 }}
                                    title="Partitioned (sharded) end-entity CRL — from CCADB JSON Array of Partitioned CRLs field. These carry the bulk of revocation entries.">
                                    shard
                                  </span>
                                )}
                                {u.crl_source === 'full' && (
                                  <span style={{ marginLeft: 5, fontSize: 8, padding: '1px 4px',
                                    borderRadius: 3, background: COLORS.bd,
                                    color: COLORS.t3 }}
                                    title="Full CRL — from CCADB 'Full CRL Issued By This CA' field. Typically an ARL (Authority Revocation List) covering sub-CA certificates.">
                                    full
                                  </span>
                                )}
                                {/* Shared CRL badge */}
                                {u.shared_with_cas?.length > 0 && (
                                  <span style={{ marginLeft: 5, fontSize: 8, padding: '1px 4px',
                                    borderRadius: 3, background: COLORS.am + '22',
                                    color: COLORS.am, fontWeight: 600 }}
                                    title={`This CRL URL is shared with: ${u.shared_with_cas.join(', ')} — indicates outsourced or delegated CRL infrastructure`}>
                                    shared ↗{u.shared_with_cas.length}
                                  </span>
                                )}
                              </td>
                              {/* Empty store column — alignment spacer */}
                              <td style={{ borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }} />
                              <td style={{ padding: '4px 10px', textAlign: 'right',
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }}>
                                <span style={{ fontSize: 9, fontWeight: u.status !== 'ok' ? 600 : 400,
                                               color: sm.color }}
                                  title={_statusDetail(u)}>
                                  {sm.label}
                                </span>
                                {u.status === 'ok' && (u.fetch_url || u.url)?.startsWith('https') &&
                                  <span style={{ fontSize: 8, color: COLORS.t3, marginLeft: 4 }}
                                    title="HTTPS — CRL fetch is confidential">🔒</span>}
                              </td>
                                                            <td style={{ borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }} />
                              <td style={{ padding: '4px 10px', fontSize: 10, textAlign: 'right',
                                           color: u.elapsed_ms > 3000 ? COLORS.am : COLORS.t3,
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }}>
                                {u.elapsed_ms != null ? `${u.elapsed_ms}` : '—'}
                              </td>
                              <td style={{ padding: '4px 10px', fontSize: 10, textAlign: 'right',
                                           color: COLORS.t3,
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }}>
                                {u.revoked_count != null ? u.revoked_count.toLocaleString() : '—'}
                              </td>
                              <td style={{ padding: '4px 10px', fontSize: 10, textAlign: 'right',
                                           color: expiryColor(u.hours_until_expiry),
                                           fontWeight: u.hours_until_expiry != null && u.hours_until_expiry < 168 ? 600 : 400,
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }}>
                                {expiryLabel(u.hours_until_expiry)}
                              </td>
                              <td style={{ padding: '4px 10px', fontSize: 10, textAlign: 'right',
                                           color: u.status === 'br_violation' ? statusMeta('br_violation').color : COLORS.t3,
                                           fontWeight: u.status === 'br_violation' ? 600 : 400,
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }}
                                title={u.validity_window_days != null
                                  ? u.br_governed
                                    ? `CRL validity window: ${u.validity_window_days}d. BR §4.9.7 limit: ${u.br_validity_limit_days ?? 366}d`
                                    : `CRL validity window: ${u.validity_window_days}d. BR not applicable (Microsoft-only or gov CA)`
                                  : 'Validity window not available'}>
                                {u.validity_window_days != null ? `${u.validity_window_days}d` : '—'}
                              </td>
                              <td style={{ padding: '4px 10px', fontSize: 9, textAlign: 'right',
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }}>
                                {u.cache_control != null
                                  ? u.cache_exceeds_window === true
                                    ? <span style={{ color: COLORS.rd, fontWeight: 600 }}
                                        title={`Cache-Control: ${u.cache_control} — max-age ${u.cache_max_age}s exceeds validity window ${Math.round((u.validity_window_days||0)*86400)}s`}>
                                        ⚠ {Math.round((u.cache_max_age||0)/3600)}h max-age
                                      </span>
                                    : <span style={{ color: COLORS.t3 }}
                                        title={`Cache-Control: ${u.cache_control}`}>
                                        {Math.round((u.cache_max_age||0)/3600)}h
                                      </span>
                                  : u.fetch_ok
                                    ? <span style={{ color: COLORS.am, fontSize: 8 }}
                                        title="No Cache-Control or Expires header. RFC 5019 §6.1: CRL servers SHOULD set max-age equal to the validity period. Without it, intermediaries may cache stale revocation data.">no caching headers</span>
                                    : <span style={{ color: COLORS.t3 }}>—</span>
                                }
                              </td>
                              <td style={{ padding: '4px 6px', textAlign: 'right',
                                           borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33` }}>
                                {u.crl_b64 && (
                                  <button
                                    style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3,
                                      border: `1px solid ${COLORS.bd}`, background: 'transparent',
                                      color: expandedCrl === u.url ? COLORS.ac : COLORS.t3,
                                      cursor: 'pointer' }}
                                    onClick={() => setExpandedCrl(expandedCrl === u.url ? null : u.url)}
                                    title="View CRL in certificate viewer">
                                    {expandedCrl === u.url ? '▲ close' : '▼ view'}
                                  </button>
                                )}
                              </td>
                            </tr>
                            {expandedCrl === u.url && u.crl_b64 && (
                              <tr>
                                <td colSpan={10} style={{
                                  padding: '0 28px 12px 28px',
                                  borderBottom: isLast ? `2px solid ${COLORS.bd}` : `1px solid ${COLORS.bd}33`,
                                  background: ALPHA.s233,
                                }}>
                                  <div style={{ padding: '8px 0 4px',
                                    display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span style={{ fontSize: 10, color: COLORS.t3,
                                      fontFamily: FONT_MONO, wordBreak: 'break-all' }}>
                                      {u.fetch_url || u.url}
                                    </span>
                                    <a href={u.fetch_url || u.url} target="_blank"
                                      rel="noopener noreferrer"
                                      style={{ fontSize: 9, color: COLORS.ac,
                                        textDecoration: 'none', whiteSpace: 'nowrap' }}>
                                      ↗ open
                                    </a>
                                  </div>
                                  <CrlViewer data={u.crl_b64} />
                                </td>
                              </tr>
                            )}
                            </React.Fragment>
                          );
                        })}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ padding: '6px 16px', fontSize: 10, color: COLORS.t3 }}>
              {filteredGroups.reduce((s, g) => s + g.urls.length, 0)} of {urls.length} URLs
              across {filteredGroups.length} of {caGroups.length} CAs.
              {' '}Revoked = certificates in the CRL at last fetch.
              {' '}Soonest expiry = earliest nextUpdate across all CA CRLs.
              {' '}URL annotations in [brackets] are informational pattern notes, not errors.
            </div>
          </div>
        );
      })()}

      {/* ── OVER TIME VIEW ── */}
      {subView === 'history' && hasEnoughHistory && (
        <div style={{ padding: '12px 16px' }}>
          <div style={{ fontSize: 12, color: COLORS.t2, marginBottom: 12 }}>
            Daily availability rate across all probed CRL URLs.
            {historySampleCount} days of data.
          </div>
          <ChartWrap height={160}>
            <AreaChart data={historyChartData} margin={{ top: 4, right: 12, left: -20, bottom: 0 }}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" stroke={COLORS.bd} strokeOpacity={0.4} />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: COLORS.t3 }}
                tickFormatter={d => d?.slice(5)} interval="preserveStartEnd" />
              <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: COLORS.t3 }}
                tickFormatter={v => `${v}%`} />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.[0]) return null;
                  const d = payload[0].payload;
                  return (
                    <div style={{ background: COLORS.s1, border: `1px solid ${COLORS.bd}`,
                      borderRadius: 6, padding: '6px 10px', fontSize: 11 }}>
                      <div style={{ color: COLORS.t3, marginBottom: 3 }}>{d.date}</div>
                      <div style={{ color: COLORS.gn }}>OK: {d.ok}/{d.total} ({d.pct}%)</div>
                      {d.stale > 0 && <div style={{ color: COLORS.am }}>Stale: {d.stale}</div>}
                      {d.mismatch > 0 && <div style={{ color: COLORS.rd }}>Issuer mismatch: {d.mismatch}</div>}
                    </div>
                  );
                }}
              />
              <ReferenceLine y={95} stroke={COLORS.am} strokeDasharray="4 2" strokeOpacity={0.5} />
              <Area type="monotone" dataKey="pct" stroke={COLORS.gn} fill={ALPHA.gn19}
                strokeWidth={1.5} dot={false} />
            </AreaChart>
          </ChartWrap>

          {/* Per-URL history table — latency and revoked count over time for URLs with issues */}
          {(() => {
            const problemUrls = urls.filter(u => u.status !== 'ok').map(u => u.url);
            if (!problemUrls.length) return null;
            return (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 500, color: COLORS.t2, marginBottom: 8 }}>
                  URLs with current issues — recent history
                </div>
                {problemUrls.slice(0, 10).map(url => {
                  const urlHistory = history[url] ?? [];
                  const recent = urlHistory.slice(-14); // last 14 days
                  const meta = urls.find(u => u.url === url);
                  return (
                    <div key={url} style={{ marginBottom: 12, paddingBottom: 12,
                      borderBottom: `1px solid ${COLORS.bd}` }}>
                      <div style={{ fontSize: 10, color: COLORS.t3, marginBottom: 4 }}>
                        <span style={{ color: COLORS.t2, fontWeight: 500 }}>{meta?.ca_owner}</span>
                        {' · '}{url.replace(/^https?:\/\//, '').slice(0, 70)}
                      </div>
                      <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                        {recent.map((e, i) => {
                          const ok = e.fetch_ok && e.parse_ok && !e.is_stale && e.issuer_match !== false;
                          return (
                            <div key={i} title={`${e.date}: ${e.status} ${e.elapsed_ms ? `(${e.elapsed_ms}ms)` : ''}`}
                              style={{ width: 12, height: 20, borderRadius: 2,
                                background: ok ? COLORS.gn : statusMeta(e.status).color,
                                opacity: 0.8 }} />
                          );
                        })}
                        {recent.length === 0 &&
                          <span style={{ fontSize: 10, color: COLORS.t3 }}>No history yet</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </div>
      )}

      {/* ── EVENTS VIEW ── */}
      {subView === 'events' && (
        <div style={scrollXStyle}>
          <table style={{ ...compactTableStyle, width: '100%' }}>
            <thead>
              <tr>
                <th style={{ padding: '6px 10px', color: COLORS.t3, fontSize: 10, textAlign: 'left' }}>Date</th>
                <th style={{ padding: '6px 10px', color: COLORS.t3, fontSize: 10, textAlign: 'left' }}>CA</th>
                <th style={{ padding: '6px 10px', color: COLORS.t3, fontSize: 10, textAlign: 'left' }}>Event</th>
                <th style={{ padding: '6px 10px', color: COLORS.t3, fontSize: 10, textAlign: 'left' }}>Detail</th>
              </tr>
            </thead>
            <tbody>
              {[...events].reverse().slice(0, 200).map((e, i) => {
                const eventColor = {
                  outage: COLORS.rd, recovered: COLORS.gn,
                  crl_expired: COLORS.rd, crl_refreshed: COLORS.gn,
                  issuer_mismatch: COLORS.rd, issuer_match_restored: COLORS.gn,
                  mass_revocation: COLORS.am, crl_reset: COLORS.am,
                }[e.event] ?? COLORS.t2;
                return (
                  <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : ALPHA.s227 }}>
                    <td style={{ padding: '5px 10px', fontSize: 10, color: COLORS.t3, borderBottom: `1px solid ${COLORS.bd}`, whiteSpace: 'nowrap' }}>{e.date}</td>
                    <td style={{ padding: '5px 10px', fontSize: 11, color: COLORS.tx, borderBottom: `1px solid ${COLORS.bd}` }}>{e.ca}</td>
                    <td style={{ padding: '5px 10px', fontSize: 10, fontWeight: 600, color: eventColor, borderBottom: `1px solid ${COLORS.bd}`, whiteSpace: 'nowrap' }}>{e.event}</td>
                    <td style={{ padding: '5px 10px', fontSize: 10, color: COLORS.t2, borderBottom: `1px solid ${COLORS.bd}` }}>{e.detail}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ padding: '6px 16px', fontSize: 10, color: COLORS.t3 }}>
            Showing most recent {Math.min(events.length, 200)} of {events.length} changes.
          </div>
        </div>
      )}
    </Card>
  );
}

export { OpsMap };
export default OpsView;
