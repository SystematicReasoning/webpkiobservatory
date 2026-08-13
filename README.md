# WebPKI Observatory

A public dashboard tracking Certificate Authority market share, trust store coverage, geographic concentration, government presence, operational incidents, governance effectiveness, and cryptographic posture across the Web PKI ecosystem.

**Live:** https://webpki.systematicreasoning.com

## What it is

The Observatory combines five public data sources — crt.sh, CCADB, Bugzilla, StatCounter, and cabforum.org — into a unified analytical view that no single source provides on its own. It is scoped to the 97 CA organizations currently trusted by at least one of the four major browser trust stores (Mozilla, Chrome, Microsoft, Apple).

## How it works

Fifteen Python scripts fetch from public sources daily, normalize the results into JSON, and commit them to the repository. A Vite build reads the JSON at compile time and produces a static React app deployed to GitHub Pages. There is no backend server.

```
pipeline/     Python — fetch from crt.sh, CCADB, Bugzilla, StatCounter, cabforum.org → data/*.json
data/         Pipeline output — committed to repo, updated daily by CI
app/          Vite + React — reads data/ at build time, produces static SPA
```

## Tabs

| Tab | Question |
|-----|----------|
| Market Share | How is certificate issuance distributed across CAs? |
| Trust Surface | What does the root infrastructure look like across the four trust stores? |
| Concentration Risk | How concentrated is certificate issuance (HHI, CR3/5/7)? |
| Long Tail Risk | Which CAs carry maximum trust with minimal issuance? |
| Geographic Risk | Where are trusted CAs headquartered by region and country? |
| Government Risk | How many trusted CAs have structural ties to governments? |
| Jurisdiction Risk | Which CAs are in jurisdictions with key compulsion laws? |
| Operational Risk | What is each CA's incident track record from Bugzilla? |
| Cryptographic Posture | What algorithms do root certificates use vs standards body recommendations? |
| Distrust History | What do 16 CA removals (2011–2024) reveal about ecosystem governance? |
| Policy Compliance | How are CAs tracking against the BR certificate validity reductions? |
| Governance Risk | How effectively do root programs govern the CAs they trust? |
| Ecosystem Participation | Who participates in CA/Browser Forum governance? |
| Audit Intelligence | Do annual audit letters reflect the compliance record CAs actually generated? |

## Pipeline scripts

| Script | Output | Purpose |
|--------|--------|---------|
| `fetch_audits.py` | `audits.json`, `bugs_by_ca.json` | Audit intelligence: fetches and parses WebTrust/ETSI audit letters (PDF), computes per-CA bug retrospectives matching Bugzilla incidents to audit periods, per-auditor detection rates, ALV-equivalent fingerprint and scope checks, letter quality scores, transparency gap |
| `fetch_and_join.py` | `market_share.json`, `intersections.json`, `geography.json`, `gov_risk.json`, `ca/*.json` | Market structure, trust store profiles, geographic and government risk |
| `fetch_root_algo.py` | `root_algorithms.json` | Root certificate cryptographic data (key family, size, hash, validity dates) |
| `fetch_browser_share.py` | `browser_coverage.json` | Browser market share → trust store web coverage estimates |
| `fetch_incidents.py` | `incidents.json`, `incident_classifications.json` | Bugzilla CA compliance bugs; LLM classification into misissuance/revocation/governance/validation |
| `fetch_rpe.py` | `root_program_effectiveness.json` | 7-phase governance pipeline: enforcement, oversight, policy leadership, trust surface, dark matter |
| `fetch_microsoft_ctl.py` | `microsoft_ctl_changelog.json` | Microsoft trust store changelog from monthly deployment notices (2020+) |
| `fetch_chrome_root_store.py` | `chrome_root_store_changelog.json` | Chrome Root Store changelog from Chromium source git history (2022+) |
| `fetch_trust_snapshots.py` | `snapshots/`, `trust_store_changelog.json` | Daily CCADB snapshots; diffs build cross-store changelog (only source for Apple changes) |
| `fetch_community.py` | `community_engagement.json` | CA/B Forum participation: org and individual Bugzilla + ballot engagement |
| `fetch_cabf_ballots.py` | `ops_cache/cabforum_ballots.json` | All CA/B Forum ballots across SC, CSC, SMC, and NS working groups |
| `fetch_br_validity_changelog.py` | `br_validity_changelog.json` | BR maximum certificate validity reduction timeline |
| `fetch_crl_health.py` | `crl_health.json`, `crl_health_history.json`, `crl_health_events.json` | CRL infrastructure health: probes every CRL URL filed in CCADB daily; checks fetch reachability, TLS quality, CRL parse validity, issuer DN match, and BR §4.9.7 validity window compliance (10-day end-entity / 12-month sub-CA). Detects outages, stale CRLs, and wrong CRL filings. |
| `fetch_compliance_growth.py` | `compliance_growth.json` | Normative obligation growth across CA/B Forum TLS BR, EVG, NS Reqs, S/MIME BR, CS BR, Mozilla MRSP, and IETF RFCs. Uses convention-aware parsers per document; tracks ballot-by-ballot obligation counts from 2012 to present. |
| `fetch_revision_history.py` | `revision_history.json` | Ballot timeline from CABF document revision tables. Provides coarse ballot-date coverage filling gaps where git tags are absent (TLS BR 2021–2024, pre-GitHub era). Used by ComplianceVelocity chart to place ballot ticks on the timeline. |
| `fetch_tab_intros.py` | `tab_intros.json` | LLM-generated tab intro text (runs after data is finalized) |
| `export_llm_snapshot.py` | `llm_snapshot.json` | Combined snapshot for LLM context export, distrust classification, and ForgeIQ integration |
| `export_ui_bundle.py` | `ui_bundle.json` | Transforms pipeline JSON into the single virtual module consumed by the Vite build |

## Data sources

| Source | What | Frequency |
|--------|------|-----------|
| [crt.sh](https://crt.sh) | Certificate populations by CA owner | Daily |
| [CCADB](https://www.ccadb.org) | Root/intermediate metadata, trust store inclusion, capabilities | Daily |
| [Bugzilla](https://bugzilla.mozilla.org) | CA Certificate Compliance incidents (2014–present) and comment history | Daily |
| [StatCounter](https://gs.statcounter.com/browser-market-share) | Browser market share for web coverage estimates | Daily |
| [cabforum.org](https://cabforum.org) | CA/B Forum ballot history across all working groups | Daily |
| [keylength.com](https://keylength.com) | Standards body cryptographic recommendations | Manual |

## Local development

```bash
cd app
npm install
PIPELINE_DATA_DIR=../data PIPELINE_DIR=../pipeline npx vite dev
```

Data is pre-committed so no pipeline run is needed to develop locally.

## Deployment

GitHub Actions runs daily at 06:00 UTC. The `update-data` job runs all pipeline scripts and commits any changes. The `build` job runs `export_ui_bundle.py`, builds the React app, and deploys to GitHub Pages.

Requires `ANTHROPIC_API_KEY` secret for incident classification and tab intro generation.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.  
See [SPEC.md](SPEC.md) for per-tab metric specifications.  
See [METHODOLOGY.md](METHODOLOGY.md) for data source details and derivation explanations.

Built by [Systematic Reasoning, Inc.](https://systematicreasoning.com)
