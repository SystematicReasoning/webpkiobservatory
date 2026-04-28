# Architecture

## System Overview

The WebPKI Observatory is a static dashboard that provides a quantitative view of the Certificate Authority ecosystem. It answers the question: **who can issue certificates trusted by web browsers, and what does that trust surface look like across market structure, geographic distribution, government exposure, operational track record, governance quality, and audit accountability?**

The system has three layers:

1. **Pipeline** — Python scripts that fetch from public data sources, normalize, enrich, and produce JSON files
2. **Build** — `export_ui_bundle.py` transforms pipeline JSON into a single optimized virtual module; Vite embeds it into the JavaScript bundle at compile time
3. **Dashboard** — A React single-page app that renders 14 analytical views from the embedded data

There is no backend server. The pipeline runs in GitHub Actions, the build produces static files, and the dashboard is served from GitHub Pages. All data is public.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  crt.sh      │     │              │     │              │     │              │     │              │
│  CCADB       │────▶│   Pipeline   │────▶│ data/*.json  │────▶│  UI Bundle   │────▶│  Vite Build  │
│  Bugzilla    │     │ (15 scripts) │     │ (committed)  │     │ export_ui_   │     │  (static     │
│  StatCounter │     │              │     │              │     │  bundle.py)  │     │   React SPA) │
│  cabforum.org│     └──────────────┘     └──────────────┘     └──────────────┘     └──────┬───────┘
└──────────────┘                                                                           │
                                                                                           ▼
                                                                                   GitHub Pages
```

## Data Flow

### Pipeline Stage (update-data job)

Fifteen Python scripts run daily at 06:00 UTC via GitHub Actions, in this order:

| Script | Input | Output | Purpose |
|--------|-------|--------|---------|
| `fetch_root_algo.py` | CCADB root PEMs | `root_algorithms.json`, PEM cache | Root cert cryptographic data — runs first because `fetch_and_join.py` uses the PEM cache |
| `fetch_and_join.py` | crt.sh API, CCADB CSV | `market_share.json`, `intersections.json`, `geography.json`, `gov_risk.json`, `ca/*.json` | Market structure, trust store profiles, geographic/government risk, BR validity status |
| `fetch_browser_share.py` | StatCounter | `browser_coverage.json` | Browser market share for web coverage estimates |
| `fetch_incidents.py` | Bugzilla REST API, Anthropic API | `incidents.json`, `bugs_by_ca.json`, `bugs_by_ca_distrusted.json`, `incident_classifications.json` | Compliance incident counts, LLM classification, self-report rates, per-CA bug detail for audit retrospective |
| `fetch_audits.py` | CCADB CSV, audit letter PDFs (CPA Canada + direct URLs), `bugs_by_ca.json`, Anthropic API | `audits.json` | Audit intelligence: fetches and LLM-parses WebTrust/ETSI audit letters; computes per-CA bug retrospectives matching each Bugzilla incident to the audit periods that covered it; per-auditor in-period detection rates; letter quality scores (0–100); transparency gap; auditor concentration and HHI |
| `fetch_microsoft_ctl.py` | learn.microsoft.com | `microsoft_ctl_changelog.json` | Microsoft trust store changelog from deployment notices (2020+) |
| `fetch_chrome_root_store.py` | Chromium Gitiles API | `chrome_root_store_changelog.json` | Chrome Root Store changelog from source git history (2022+) |
| `fetch_trust_snapshots.py` | CCADB CSV | `snapshots/YYYY-MM-DD.json`, `trust_store_changelog.json` | Daily trust store state snapshots; diffs build changelog (only source for Apple changes) |
| `fetch_rpe.py` | Bugzilla, CCADB, `cabforum_ballots.json`, `distrusted.json`, `comment_classifications.json` | `root_program_effectiveness.json` | 7-phase governance pipeline: enforcement, oversight, policy leadership, trust surface, dark matter |
| `fetch_community.py` | Bugzilla, `cabforum_ballots.json`, CABF member list | `community_engagement.json` | CA/B Forum participation by organization and individual |
| `fetch_cabf_ballots.py` | cabforum.org | `ops_cache/cabforum_ballots.json` | All SC/CSC/SMC/NS ballots with proposers, endorsers, vote results |
| `fetch_br_validity_changelog.py` | Pipeline data | `br_validity_changelog.json` | BR maximum validity reduction timeline |
| `fetch_compliance_growth.py` | CA/B Forum GitHub, IETF RFCs, Mozilla MRSP, NIS2, NIST SP 800-53 | `compliance_growth.json` | Normative obligation count over time across major regulatory sources; uses convention-aware parsers for different document formats |
| `fetch_tab_intros.py` | `llm_snapshot.json`, Anthropic API | `tab_intros.json` | LLM-generated dynamic intro text for each tab |
| `export_llm_snapshot.py` | All pipeline outputs | `llm_snapshot.json`, topic-sharded snapshots | Combined snapshot for LLM context export and ForgeIQ integration; sharded by topic for context-window efficiency |

**Note on `classify_comments.py`:** This script is a standalone pre-processor for Bugzilla oversight comment classification. It runs separately (not as part of the daily CI sequence) to build up `ops_cache/comment_classifications.json` incrementally. `fetch_rpe.py` reads this cache at runtime; when the cache is cold, `technical` defaults to False (conservative: unknown comments are not counted as substantive). `fetch_incidents.py` handles incident-level classification; `classify_comments.py` handles per-comment governance/technical classification for root program oversight analysis.

Pipeline outputs are committed to the repository. The data directory is a versioned, auditable record of the WebPKI's state over time.

**Curated data** lives in `pipeline/distrust/distrusted.json` — 16 CA removal events with per-store distrust dates, compliance posture classification, distrust pathway, and contributing factor tags. This file is the single source of truth for both the Distrust History tab and the Governance Risk enforcement metrics. Updating it once updates both tabs.

**Ops cache** (`pipeline/ops_cache/`) stores expensive API responses between runs: Bugzilla bug lists, comment bodies, CABF ballot data, Microsoft CTL notices, Chrome root store git diffs, comment classifications, compliance growth data. Cache keys include content hashes so stale entries are automatically invalidated when upstream data changes.

**`incident_classifications.json`** is git-tracked (not just cached) because it represents accumulated LLM classifications for 1,700+ Bugzilla comments. Losing this cache would require reprocessing the full comment history at significant API cost.

### Build Stage (build job, runs after update-data)

**`export_ui_bundle.py`** reads all pipeline JSON files and produces `data/ui_bundle.json` — a single file containing all data the dashboard needs, pre-shaped for the React app. This script applies:

1. **Trust-scope filtering** — Only CAs with `trust_store_count > 0` or a `parent_ca` relationship appear in current-ecosystem analysis. 249 CA owners are tracked; 97 are currently trusted.

2. **Field normalization** — Pipeline JSON field names (snake_case) are mapped to React app names (camelCase). `ca_owner` → `caOwner`, `trust_store_count` → `storeCount`, etc.

3. **BR validity status** — Each CA gets a `brStatus` field (`violation` / `risk_2027` / `risk_2029` / `compliant` / `not_applicable`) computed from usage period against BR thresholds. Only active TLS issuers qualify: `tls_capable=True`, `unexpired_precerts ≥ 1,000`, trusted by at least one current store. CAs that don't meet this gate get `not_applicable` rather than a misleading classification — PKIoverheid has a usage period of 5,475 days because it issued long-lived non-TLS certs years ago, not because it's currently violating the BR.

4. **Country normalization** — CCADB uses inconsistent country names. These are normalized to canonical forms for cross-referencing.

5. **Distrust overrides** — CAs with distrust events get their `storeCount` zeroed and `trustedBy` cleared, regardless of what CCADB currently shows. This handles the lag between operational distrust and CCADB record updates.

The Vite plugin (`vite.config.js`) reads `ui_bundle.json` at build time and embeds it as the virtual ES module `virtual:pipeline-data`. No runtime API calls, no loading states, no waterfall fetches.

### Dashboard Stage

The React app renders 15 tabs from the embedded data via a shared `PipelineContext`. Each tab is code-split via `React.lazy()` so only the active tab's code is loaded.

**Rendering pattern:** Every view component follows the same structure:
1. Destructure needed data from `usePipeline()`
2. If required data field is absent, return `<DataPending />` — never fall back to wrong behavior
3. Compute derived metrics via `useMemo()`
4. Render: stat cards → charts/maps → detailed tables
5. `<MethodologyCard>` at the bottom explaining sources, derivations, and limitations

## Key Architectural Decisions

### Why static?

The data changes once per day. A server-rendered or API-backed architecture adds operational complexity for zero benefit. Static deployment means the dashboard loads instantly, works offline after first load, and costs nothing to serve.

### Why commit data to the repo?

The data directory is a versioned, auditable record. Every daily pipeline run that produces new data gets a commit with a diff showing exactly what changed. This makes it easy to audit anomalies, debug pipeline regressions, and reconstruct historical state without maintaining a separate database.

### Why embed data at build time?

Embedding data in the JavaScript bundle eliminates the waterfall problem: no runtime JSON fetches, no loading spinners, no failure modes. For ~2MB of source data this is the right tradeoff. The alternative (runtime fetch from GitHub Pages) would add visible loading delay and error handling complexity to every tab.

### Why `export_ui_bundle.py` as a separate step?

The pipeline produces data in a format useful for many purposes (historical analysis, debugging, LLM export, ForgeIQ integration). The build-facing transformation — field renaming, trust scope filtering, BR status classification — belongs in a separate step, not mixed into each pipeline script. `export_ui_bundle.py` is the single place where pipeline data becomes dashboard data.

**Important for local development:** `ui_bundle.json` is committed to the repo but is only regenerated during the CI build step, after all pipeline scripts have run. If you manually patch any `data/*.json` file (e.g. `audits.json`, `incidents.json`), you must also run `python pipeline/export_ui_bundle.py` before building the app, or the bundle will be stale and the dashboard will show old data. `pipeline/verify_bundle.py` checks for the most common staleness symptom (missing `bug_retrospective`) and warns if detected.

### Why `DataPending` instead of fallbacks?

When a required data field is missing from the bundle (because the pipeline field is newer than the last build), the correct behavior is to show a pending state, not silently degrade to an older behavior that produces wrong results. Fallbacks mask errors and produce inconsistent user experiences depending on which pipeline version produced the data. `DataPending` makes the missing dependency explicit.

### Why React + Vite?

The dashboard has interactive elements (expandable rows, sortable tables, zoomable maps, filter controls, paginated lists) that require a component framework. Vite provides fast builds and the virtual module plugin. Recharts and d3-geo provide the visualization layer.

## Component Architecture

```
App.jsx
├── PipelineProvider (context: all pipeline data, shared computations)
│   ├── TabBar (hash-based routing, 14 tabs)
│   ├── ErrorBoundary (per-tab crash isolation)
│   │   └── [Tab Component] (lazy-loaded)
│   │       ├── StatCard, Card, CardTitle (layout atoms)
│   │       ├── MethodologyCard, MethodologyItem (shared methodology pattern)
│   │       ├── GeoMap, ChartWrap (visualization wrappers)
│   │       ├── TrustDots, Badge, RateDot, Dot (data display atoms)
│   │       ├── TrustExpiration, TrustHeatmap (Trust Surface subcomponents)
│   │       ├── ComplexityKPI, ComplianceVelocity (Compliance Growth subcomponents)
│   │       ├── DataPending (shown when required data field absent)
│   │       └── CADetail (shared expandable CA detail panel, used across tabs)
│   └── Footer (data freshness, methodology disclosure)
└── ErrorBoundary (app-level fallback)
```

## File Structure

```
webpki-observatory/
├── pipeline/                              # Data collection (Python)
│   ├── fetch_and_join.py                  # crt.sh + CCADB → market/trust/geo/gov/brStatus
│   ├── fetch_root_algo.py                 # CCADB PEMs → root algorithm analysis
│   ├── fetch_browser_share.py             # StatCounter → browser coverage
│   ├── fetch_incidents.py                 # Bugzilla → incident classification (LLM)
│   ├── fetch_audits.py                    # CCADB + audit letter PDFs → audit intelligence
│   ├── fetch_rpe.py                       # Bugzilla+CCADB+ballots → governance risk (7 phases)
│   ├── fetch_microsoft_ctl.py             # learn.microsoft.com → Microsoft trust store changelog
│   ├── fetch_chrome_root_store.py         # Chromium Gitiles → Chrome Root Store changelog
│   ├── fetch_trust_snapshots.py           # Daily CCADB snapshot → cross-store changelog
│   ├── fetch_community.py                 # Bugzilla+cabforum → CA/B Forum participation
│   ├── fetch_cabf_ballots.py              # cabforum.org → SC/CSC/SMC/NS ballot history
│   ├── fetch_br_validity_changelog.py     # BR validity reduction timeline
│   ├── fetch_compliance_growth.py         # CABF/IETF/Mozilla/NIS2/NIST → obligation growth
│   ├── fetch_tab_intros.py                # LLM-generated tab intro text
│   ├── fetch_revision_history.py          # CABF document revision tables → ballot timeline
│   ├── classify_comments.py               # Standalone LLM pre-processor for oversight comments
│   ├── export_llm_snapshot.py             # Combined snapshot for LLM/ForgeIQ export (sharded)
│   ├── export_ui_bundle.py                # Pipeline JSON → ui_bundle.json (build input)
│   ├── obligation_parsers.py              # Convention-aware parsers for regulatory documents
│   ├── utils.py                           # Shared pipeline utilities
│   ├── config.py                          # Pipeline configuration constants
│   ├── verify_bundle.py                   # Post-build bundle staleness check
│   ├── distrust/
│   │   └── distrusted.json                # Curated distrust events — single source of truth
│   ├── ops_cache/                         # Cached API responses (gitignored except classifications)
│   │   ├── bugs_raw.json                  # Bugzilla bug list cache
│   │   ├── comments_cache.json            # Bugzilla comment body cache
│   │   ├── cabforum_ballots.json          # CA/B Forum ballot data
│   │   ├── comment_classifications.json   # LLM governance/technical classifications
│   │   ├── microsoft_ctl_cache.json       # Microsoft deployment notice cache
│   │   ├── chrome_root_store_cache.json   # Chromium commit diff cache
│   │   └── compliance_growth_cache.json   # Regulatory document fetch cache
│   ├── audit_pdf_cache/                   # Audit letter PDF cache (90-day TTL, gitignored)
│   ├── incident_classifications.json      # LLM incident classifications (git-tracked)
│   ├── gov_classifications.json           # Manually curated government CA ties
│   ├── name_mappings.json                 # crt.sh ↔ CCADB name normalization
│   └── enrichments.json                   # Manual capability overrides
├── data/                                  # Pipeline output (committed, versioned)
│   ├── market_share.json                  # 249 CAs ranked by issuance (includes brStatus)
│   ├── intersections.json                 # Trust store overlap matrix
│   ├── geography.json                     # Regional aggregation
│   ├── gov_risk.json                      # Government CA classifications
│   ├── incidents.json                     # Bugzilla compliance incidents + yearsByClass
│   ├── bugs_by_ca.json                    # Per-CA incident timeline (active CAs)
│   ├── bugs_by_ca_distrusted.json         # Per-CA incident timeline (distrusted CAs)
│   ├── incident_classifications.json      # LLM bug classifications (git-tracked, ~1700 entries)
│   ├── audits.json                        # Per-CA audit profiles + auditor concentration
│   ├── jurisdiction_risk.json             # Key seizure / compulsion laws by jurisdiction
│   ├── root_algorithms.json               # Root cert cryptographic data (335 roots)
│   ├── browser_coverage.json              # Browser → root program mapping
│   ├── root_program_effectiveness.json    # Governance risk metrics (7-phase pipeline)
│   ├── community_engagement.json          # CA/B Forum participation (62 orgs, 126 individuals)
│   ├── compliance_growth.json             # Normative obligation counts over time
│   ├── revision_history.json              # CABF document revision/ballot timeline
│   ├── ca_details.json                    # Extended per-CA detail data
│   ├── microsoft_ctl_changelog.json       # Microsoft trust store change history
│   ├── chrome_root_store_changelog.json   # Chrome Root Store change history
│   ├── trust_store_changelog.json         # Cross-store trust change history (from snapshots)
│   ├── br_validity_changelog.json         # BR maximum validity reduction timeline
│   ├── tab_intros.json                    # LLM-generated tab intro text
│   ├── llm_snapshot.json                  # Combined snapshot (current)
│   ├── llm_snapshot_YYYY-MM-DD.json       # Daily snapshot archive
│   ├── llm_snapshot_distrust.json         # Topic-sharded: distrust events
│   ├── llm_snapshot_governance.json       # Topic-sharded: governance data
│   ├── llm_snapshot_index.json            # Topic-sharded: index/metadata
│   ├── llm_snapshot_market.json           # Topic-sharded: market structure
│   ├── llm_snapshot_risk.json             # Topic-sharded: risk data
│   ├── history.json                       # Historical summary data
│   ├── ui_bundle.json                     # Build input: all pipeline data, pre-shaped (~560KB)
│   ├── metadata.json                      # Pipeline run timestamps and freshness tracking
│   ├── snapshots/                         # Daily CCADB trust store snapshots
│   └── ca/                               # Per-CA detail files (roots, intermediates, PEMs)
├── app/                                   # Dashboard (React + Vite)
│   ├── vite.config.js                     # Virtual module plugin (reads ui_bundle.json)
│   ├── scripts/validate-data.cjs          # Build-time data validation (fails build on critical errors)
│   ├── src/
│   │   ├── App.jsx                        # Shell: 14 tabs, hash routing, header, footer
│   │   ├── ErrorBoundary.jsx              # Per-tab crash isolation
│   │   ├── PipelineContext.jsx            # Shared data context (trustedCAs, rpeData, etc.)
│   │   ├── data.js                        # Re-exports from virtual:pipeline-data
│   │   ├── constants.js                   # Theme colors, display names, milestone definitions
│   │   ├── helpers.js                     # Shared derived metric functions
│   │   ├── styles.js                      # Shared style objects
│   │   ├── types.ts                       # TypeScript type definitions for CA data shape
│   │   └── components/
│   │       ├── shared.jsx                 # Atoms: Card, StatCard, GeoMap, DataPending, TrustDots
│   │       ├── CADetail.jsx               # Expandable per-CA detail panel (used across tabs)
│   │       ├── TrustExpiration.jsx        # Trust Surface: root expiration timeline
│   │       ├── TrustHeatmap.jsx           # Trust Surface: root expiration heatmap
│   │       ├── ComplexityKPI.jsx          # Compliance Growth: KPI cards
│   │       ├── ComplianceVelocity.jsx     # Compliance Growth: velocity chart
│   │       ├── ComplianceView.jsx         # Compliance Growth: composite view
│   │       ├── MarketView.jsx             # Tab 1: Market Share
│   │       ├── TrustView.jsx              # Tab 2: Trust Surface
│   │       ├── ConcView.jsx               # Tab 3: Concentration Risk
│   │       ├── TailView.jsx               # Tab 4: Long Tail Risk
│   │       ├── GeoView.jsx                # Tab 5: Geographic Risk
│   │       ├── GovView.jsx                # Tab 6: Government Risk
│   │       ├── JurisdictionView.jsx       # Tab 7: Jurisdiction Risk
│   │       ├── OpsView.jsx                # Tab 8: Operational Risk
│   │       ├── CryptoView.jsx             # Tab 9: Cryptographic Posture
│   │       ├── DistrustView.jsx           # Tab 10: Distrust History
│   │       ├── PolicyView.jsx             # Tab 11: Policy Compliance
│   │       ├── GovernanceRiskView.jsx     # Tab 12: Governance Risk
│   │       ├── CommunityView.jsx          # Tab 13: Ecosystem Participation
│   │       └── AuditView.jsx              # Tab 14: Audit Intelligence
│   └── package.json
└── .github/workflows/deploy.yml           # Daily pipeline + build + deploy (Node.js 24)
```

## CI/CD

The GitHub Actions workflow has two jobs:

**update-data** (~8 minutes): Runs all 15 pipeline scripts, commits changed data files, saves ops cache. `classify_comments.py` is not part of the daily sequence — it runs as a separate workflow step when new Bugzilla comments need classification.

**build** (depends on update-data, ~3 minutes): Checks out the freshly committed data, runs `export_ui_bundle.py`, installs npm deps, runs `validate-data.cjs` (fails build on critical errors), runs Vite build, injects SEO content, uploads Pages artifact.

**deploy**: Deploys the artifact to GitHub Pages.

The workflow uses `concurrency: group` so only one run executes at a time — manual dispatches cancel in-progress scheduled runs rather than queueing behind them.
