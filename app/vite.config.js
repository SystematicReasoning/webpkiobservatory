import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";
import { readFileSync, writeFileSync, existsSync, mkdirSync, statSync, utimesSync } from "fs";

/**
 * Vite plugin that materializes the pipeline UI bundle for the app.
 *
 * Two outputs:
 *
 *   1. A virtual ES module (`virtual:pipeline-data`) that exports ONLY
 *      fields needed synchronously at module-eval time. Today that's just
 *      SLUG_NAMES, used by helpers.js. Keep this list tight — every field
 *      here gets parsed, minified, and source-mapped by Rollup, which is
 *      what caused the OOM that motivated this refactor.
 *
 *   2. A copy of the full ui_bundle.json into `public/`, which Vite passes
 *      through to `dist/` unchanged. The app fetches it at runtime from
 *      `${BASE_URL}ui_bundle.json` — see PipelineContext.jsx.
 *
 *   Why: ui_bundle.json grew past ~50MB once RPE_DATA was added (6000+
 *   Bugzilla comments). Inlining it as a JS module via JSON.stringify ran
 *   Vite/Rollup past Node's default 4GB heap during chunk rendering.
 *   Serving it as a static asset costs the build nothing and lets the
 *   browser cache it separately from app code.
 */
function pipelineDataPlugin() {
  const virtualModuleId = "virtual:pipeline-data";
  const resolvedId = "\0" + virtualModuleId;

  // Fields that need to be available synchronously via `import` at module
  // evaluation time. Everything else is fetched at runtime. Keep this set
  // small — only add a field if you have a concrete reason it can't go
  // through PipelineContext.
  const SYNCHRONOUS_FIELDS = ["SLUG_NAMES"];

  function loadBundle() {
    const dataDir = process.env.PIPELINE_DATA_DIR || resolve(__dirname, "../data");
    const bundlePath = resolve(dataDir, "ui_bundle.json");

    if (!existsSync(bundlePath)) {
      console.error("[pipeline-data] ERROR: ui_bundle.json not found at", bundlePath);
      console.error("[pipeline-data] Run: python pipeline/export_ui_bundle.py");
      throw new Error("ui_bundle.json not found. Run pipeline/export_ui_bundle.py first.");
    }

    return { bundlePath, bundle: JSON.parse(readFileSync(bundlePath, "utf8")) };
  }

  // Copy ui_bundle.json into public/ so Vite ships it to dist/ as a static
  // asset. Idempotent — skips the copy when source and destination have
  // matching mtimes, so the dev server doesn't churn on every restart.
  function publishBundle(bundlePath) {
    const publicDir = resolve(__dirname, "public");
    if (!existsSync(publicDir)) mkdirSync(publicDir, { recursive: true });

    const dest = resolve(publicDir, "ui_bundle.json");
    if (existsSync(dest)) {
      const srcStat = statSync(bundlePath);
      const dstStat = statSync(dest);
      if (Math.floor(srcStat.mtimeMs) === Math.floor(dstStat.mtimeMs)) return dest;
    }

    // Copy + preserve mtime for the idempotency check above.
    const buf = readFileSync(bundlePath);
    writeFileSync(dest, buf);
    const srcStat = statSync(bundlePath);
    try { utimesSync(dest, srcStat.atime, srcStat.mtime); } catch {}
    return dest;
  }

  return {
    name: "pipeline-data",

    // Runs at the start of both `vite build` and `vite dev`. This is where
    // we copy ui_bundle.json into public/ so it ends up in dist/ at build
    // time and is served by the dev server in serve mode.
    buildStart() {
      const { bundlePath, bundle } = loadBundle();
      publishBundle(bundlePath);

      console.log("[pipeline-data]",
        bundle.CA_DATA?.length || 0, "CAs,",
        Object.keys(bundle.ROOTS || {}).length, "CAs with roots,",
        Object.values(bundle.ROOTS || {}).reduce((s, a) => s + a.length, 0), "roots,",
        (bundle.INCIDENTS_DATA?.cas || []).length, "CAs with incidents");

      if (bundle.DISTRUST_DATA?.events) {
        console.log("[pipeline-data] Distrust:", bundle.DISTRUST_DATA.events.length, "events");
      }
      if (bundle.RPE_DATA?.meta) {
        console.log("[pipeline-data] RPE:",
          bundle.RPE_DATA.meta.bugs_with_comments || 0, "bugs analyzed,",
          bundle.RPE_DATA.meta.total_comments_analyzed || 0, "comments");
      }

      const fullBytes = JSON.stringify(bundle).length;
      const syncBytes = SYNCHRONOUS_FIELDS.reduce(
        (n, k) => n + (bundle[k] ? JSON.stringify(bundle[k]).length : 0), 0);
      console.log("[pipeline-data] Bundle:",
        (fullBytes / 1024 / 1024).toFixed(1), "MB total,",
        (syncBytes / 1024).toFixed(1), "KB inlined,",
        ((fullBytes - syncBytes) / 1024 / 1024).toFixed(1), "MB fetched at runtime");
    },

    resolveId(id) {
      if (id === virtualModuleId) return resolvedId;
    },

    load(id) {
      if (id !== resolvedId) return;
      const { bundle } = loadBundle();
      const sync = Object.fromEntries(
        SYNCHRONOUS_FIELDS.map((k) => [k, bundle[k]]),
      );
      return Object.entries(sync)
        .map(([k, v]) => `export const ${k} = ${JSON.stringify(v)};`)
        .join("\n");
    },
  };
}

export default defineConfig({
  plugins: [react(), pipelineDataPlugin()],
  base: process.env.VITE_BASE_PATH || "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 3000,
  },
});
