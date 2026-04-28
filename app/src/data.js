/**
 * Pipeline data layer.
 *
 * All pipeline JSON is injected at build time via the virtual:pipeline-data
 * Vite plugin. This module re-exports everything under clear names so views
 * never import from the virtual module directly.
 *
 * Property-level names (d.v, d.ca, d.co, etc.) remain single-letter for now.
 * The mapping is documented in vite.config.js and SESSION_HANDOFF.md.
 */
import pipelineData from 'virtual:pipeline-data';

export const CA_DATA = pipelineData.CA_DATA;
export const BR_VALIDITY = pipelineData.BR_VALIDITY;
export const BROWSER_COVERAGE = pipelineData.BROWSER_COVERAGE;
export const INTERSECTIONS = pipelineData.INTERSECTIONS;
export const GEOGRAPHY = pipelineData.GEOGRAPHY;
export const GOV_RISK = pipelineData.GOV_RISK;
export const INCIDENTS_DATA = pipelineData.INCIDENTS_DATA;
export const ROOTS = pipelineData.ROOTS;
export const INCIDENT_COUNTS = pipelineData.INCIDENT_COUNTS;
export const SLUG_NAMES = pipelineData.SLUG_NAMES;
export const JURISDICTION_RISK = pipelineData.JURISDICTION_RISK;
export const ROOT_ALGO = pipelineData.ROOT_ALGO;
export const DISTRUST_DATA = pipelineData.DISTRUST_DATA;
export const RPE_DATA = pipelineData.RPE_DATA;
export const COMMUNITY_DATA = pipelineData.COMMUNITY_DATA;
export const CHROME_CHANGELOG = pipelineData.CHROME_CHANGELOG;
export const TAB_INTROS = pipelineData.TAB_INTROS;
export const COMPLIANCE_DATA = pipelineData.COMPLIANCE_DATA;
export const AUDITS_DATA = pipelineData.AUDITS_DATA;
export const CRL_HEALTH_DATA = pipelineData.CRL_HEALTH_DATA;
export const CRL_HEALTH_HISTORY = pipelineData.CRL_HEALTH_HISTORY;
export const CRL_HEALTH_EVENTS = pipelineData.CRL_HEALTH_EVENTS;
