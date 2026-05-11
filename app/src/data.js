/**
 * Pipeline data layer (synchronous slice).
 *
 * Only re-exports fields that are needed synchronously at module-eval
 * time — currently just SLUG_NAMES, used by helpers.js for slug→name
 * lookups in pure helper functions that can't take props or context.
 *
 * Everything else (CA_DATA, ROOTS, INCIDENTS_DATA, RPE_DATA, ...) is
 * fetched at runtime from `${BASE_URL}ui_bundle.json` in
 * PipelineContext.jsx. See vite.config.js for the build-time wiring.
 */
import { SLUG_NAMES } from 'virtual:pipeline-data';

export { SLUG_NAMES };
