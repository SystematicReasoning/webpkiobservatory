/**
 * PipelineContext: provides all pipeline data to the component tree.
 *
 * The full ui_bundle.json (CA_DATA, ROOTS, INCIDENTS_DATA, RPE_DATA,
 * AUDITS_DATA, etc.) is fetched at runtime from `${BASE_URL}ui_bundle.json`
 * — Vite copies it from `data/ui_bundle.json` into `public/` at build
 * time, and Pages serves it as a plain static asset.
 *
 * Why runtime fetch and not Vite inline:
 *   - Inlining the bundle (~50MB once RPE_DATA landed) blew Rollup past
 *     Node's 4GB heap during chunk rendering.
 *   - Fetched JSON is cached by the browser separately from app code, so
 *     pure code releases don't re-download data and vice versa.
 *
 * Render gating: children render `null` until the bundle resolves, so
 * downstream components never see empty CA arrays. This trades a tiny
 * initial spinner for not having to make every consumer defensive about
 * an "is loaded yet" state.
 *
 * CRL data (~35MB at 9856+ URLs) is fetched separately and lazily — it's
 * only needed by the Operational Risk tab, so we don't gate boot on it.
 */
import React, { createContext, useContext, useMemo, useState, useEffect } from 'react';
import { COLORS, FONT_SANS } from './constants';

export const PipelineContext = createContext(null);

const BUNDLE_URL = `${import.meta.env.BASE_URL}ui_bundle.json`;

function BundleLoadError({ error }) {
  return (
    <div style={{
      minHeight: '100vh',
      background: COLORS.bg,
      color: COLORS.tx,
      fontFamily: FONT_SANS,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
    }}>
      <div style={{ maxWidth: 520, fontSize: 13, lineHeight: 1.6 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Could not load WebPKI data.</div>
        <div style={{ color: COLORS.t2, marginBottom: 12 }}>
          Failed to fetch <code>{BUNDLE_URL}</code>.
        </div>
        <div style={{ color: COLORS.t3, fontSize: 11, fontFamily: 'monospace' }}>
          {String(error?.message || error)}
        </div>
      </div>
    </div>
  );
}

function BundleLoading() {
  return (
    <div style={{
      minHeight: '100vh',
      background: COLORS.bg,
      color: COLORS.t3,
      fontFamily: FONT_SANS,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 11,
    }}>
      Loading WebPKI data...
    </div>
  );
}

export function PipelineProvider({ children }) {
  const [bundle, setBundle]   = useState(null);
  const [error,  setError]    = useState(null);

  const [crlFetched,        setCrlFetched]        = useState(null);
  const [crlHistoryFetched, setCrlHistoryFetched] = useState(null);
  const [crlEventsFetched,  setCrlEventsFetched]  = useState(null);

  // Boot fetch of the main bundle.
  useEffect(() => {
    let cancelled = false;
    fetch(BUNDLE_URL, { cache: 'force-cache' })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${BUNDLE_URL}`);
        return r.json();
      })
      .then((d) => { if (!cancelled) setBundle(d); })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, []);

  // CRL data (large, tab-specific). Lazy-fetch in parallel, no gate.
  useEffect(() => {
    fetch('crl_health.json')
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setCrlFetched(d); })
      .catch(() => {});
    fetch('crl_health_history.json')
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setCrlHistoryFetched(d); })
      .catch(() => {});
    fetch('crl_health_events.json')
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setCrlEventsFetched(d); })
      .catch(() => {});
  }, []);

  const value = useMemo(() => {
    if (!bundle) return null;

    // Defensive defaults — if a pipeline field is missing or malformed,
    // provide a safe empty value so downstream components don't crash.
    const caData            = Array.isArray(bundle.CA_DATA)     ? bundle.CA_DATA     : [];
    const brValidity        = Array.isArray(bundle.BR_VALIDITY) ? bundle.BR_VALIDITY : [];
    const browserCoverage   = bundle.BROWSER_COVERAGE || { chrome: 0, apple: 0, mozilla: 0, microsoft: 0 };
    const intersections     = bundle.INTERSECTIONS   || { rc: [], oc: [], ps: {}, a4: { r: 0, o: 0 }, ao: 0, tr: 0, activeOwners: 0, totalRoots: 0 };
    const geography         = Array.isArray(bundle.GEOGRAPHY) ? bundle.GEOGRAPHY : [];
    const govRisk           = bundle.GOV_RISK        || { t: {}, n: 0, cas: [] };
    const incidentsData     = bundle.INCIDENTS_DATA  || { total: 0, total_with_distrusted: 0, ca_count: 0, ca_count_with_distrusted: 0, years: [], categories: [], cas: [], yearsByClass: [], fingerprints: [], distrusted_excluded: [], distrusted_years: [] };
    const roots             = bundle.ROOTS           || {};
    const incidentCounts    = bundle.INCIDENT_COUNTS || {};
    const jurisdictionRisk  = bundle.JURISDICTION_RISK || { jurisdictions: [] };
    const rootAlgo          = Array.isArray(bundle.ROOT_ALGO) ? bundle.ROOT_ALGO : [];
    const distrustData      = bundle.DISTRUST_DATA   || { events: [], stats: {}, taxonomy: {} };
    const rpeData           = bundle.RPE_DATA        || null;
    const communityData     = bundle.COMMUNITY_DATA  || null;
    const chromeChangelog   = bundle.CHROME_CHANGELOG || null;
    const tabIntros         = bundle.TAB_INTROS?.intros || {};
    const complianceData    = bundle.COMPLIANCE_DATA || null;
    const auditsData        = bundle.AUDITS_DATA     || null;
    const crlHealthData     = crlFetched        || bundle.CRL_HEALTH_DATA    || null;
    const crlHealthHistory  = crlHistoryFetched || bundle.CRL_HEALTH_HISTORY || null;
    const crlHealthEvents   = crlEventsFetched  || bundle.CRL_HEALTH_EVENTS  || null;
    const trustedCAs        = caData.filter((d) => d.storeCount > 0 || d.parent);

    return {
      caData, brValidity, browserCoverage, intersections, geography,
      govRisk, incidentsData, roots, incidentCounts, jurisdictionRisk,
      rootAlgo, distrustData, rpeData, communityData, chromeChangelog,
      tabIntros, trustedCAs, complianceData, auditsData,
      crlHealthData, crlHealthHistory, crlHealthEvents,
    };
  }, [bundle, crlFetched, crlHistoryFetched, crlEventsFetched]);

  if (error)  return <BundleLoadError error={error} />;
  if (!value) return <BundleLoading />;

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>;
}

/** Hook to access pipeline data from any component */
export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error('usePipeline must be used within PipelineProvider');
  return ctx;
}
