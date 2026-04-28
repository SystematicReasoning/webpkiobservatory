/**
 * PipelineContext: provides all pipeline data to the component tree.
 *
 * CRL data is fetched at runtime (not bundled) — crl_health.json is
 * ~35MB at 9856+ URLs, too large for the Vite bundle.
 */
import React, { createContext, useContext, useMemo, useState, useEffect } from 'react';
import {
  CA_DATA, BR_VALIDITY, BROWSER_COVERAGE, INTERSECTIONS, GEOGRAPHY,
  GOV_RISK, INCIDENTS_DATA, ROOTS, INCIDENT_COUNTS, JURISDICTION_RISK,
  ROOT_ALGO, DISTRUST_DATA, RPE_DATA, COMMUNITY_DATA, CHROME_CHANGELOG,
  TAB_INTROS, COMPLIANCE_DATA, AUDITS_DATA,
  CRL_HEALTH_DATA, CRL_HEALTH_HISTORY, CRL_HEALTH_EVENTS,
} from './data';

export const PipelineContext = createContext(null);

export function PipelineProvider({ children }) {
  const [crlFetched, setCrlFetched] = useState(null);
  const [crlHistoryFetched, setCrlHistoryFetched] = useState(null);
  const [crlEventsFetched, setCrlEventsFetched] = useState(null);

  useEffect(() => {
    fetch('crl_health.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setCrlFetched(d); })
      .catch(() => {});
    fetch('crl_health_history.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setCrlHistoryFetched(d); })
      .catch(() => {});
    fetch('crl_health_events.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setCrlEventsFetched(d); })
      .catch(() => {});
  }, []);

  const value = useMemo(
    () => {
      // Defensive defaults: if a pipeline field is missing or malformed,
      // provide a safe empty value so components don't crash.
      const caData = Array.isArray(CA_DATA) ? CA_DATA : [];
      const brValidity = Array.isArray(BR_VALIDITY) ? BR_VALIDITY : [];
      const browserCoverage = BROWSER_COVERAGE || { chrome: 0, apple: 0, mozilla: 0, microsoft: 0 };
      const intersections = INTERSECTIONS || { rc: [], oc: [], ps: {}, a4: { r: 0, o: 0 }, ao: 0, tr: 0, activeOwners: 0, totalRoots: 0 };
      const geography = Array.isArray(GEOGRAPHY) ? GEOGRAPHY : [];
      const govRisk = GOV_RISK || { t: {}, n: 0, cas: [] };
      const incidentsData = INCIDENTS_DATA || { total: 0, total_with_distrusted: 0, ca_count: 0, ca_count_with_distrusted: 0, years: [], categories: [], cas: [], yearsByClass: [], fingerprints: [], distrusted_excluded: [], distrusted_years: [] };
      const roots = ROOTS || {};
      const incidentCounts = INCIDENT_COUNTS || {};
      const jurisdictionRisk = JURISDICTION_RISK || { jurisdictions: [] };
      const rootAlgo = Array.isArray(ROOT_ALGO) ? ROOT_ALGO : [];
      const distrustData = DISTRUST_DATA || { events: [], stats: {}, taxonomy: {} };
      const rpeData = RPE_DATA || null;
      const communityData = COMMUNITY_DATA || null;
      const chromeChangelog = CHROME_CHANGELOG || null;
      const tabIntros = TAB_INTROS?.intros || {};
      const complianceData = COMPLIANCE_DATA || null;
      const auditsData = AUDITS_DATA || null;
      const crlHealthData    = crlFetched        || CRL_HEALTH_DATA    || null;
      const crlHealthHistory = crlHistoryFetched || CRL_HEALTH_HISTORY || null;
      const crlHealthEvents  = crlEventsFetched  || CRL_HEALTH_EVENTS  || null;
      const trustedCAs = caData.filter((d) => d.storeCount > 0 || d.parent);

      return {
        caData, brValidity, browserCoverage, intersections, geography,
        govRisk, incidentsData, roots, incidentCounts, jurisdictionRisk,
        rootAlgo, distrustData, rpeData, communityData, chromeChangelog,
        tabIntros, trustedCAs, complianceData, auditsData,
        crlHealthData, crlHealthHistory, crlHealthEvents,
      };
    },
    [crlFetched, crlHistoryFetched, crlEventsFetched],
  );

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>;
}

/** Hook to access pipeline data from any component */
export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error('usePipeline must be used within PipelineProvider');
  return ctx;
}
