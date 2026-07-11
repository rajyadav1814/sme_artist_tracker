# sme_artistTracker — Sony Music Entertainment Artist Intelligence Dashboard

Daily-refresh web app that tracks a curated roster of regional Latin and Lusophone artists across Sony Music Entertainment's divisions (Sony Music Latin, Sony Music Brasil, Sony Music Spain, Sony Music Mexico) plus select non-Sony artists of strategic interest. Harvests social media metrics, computes 11 KPIs per artist (10 social/streaming/press + 1 Apple Music catalog activity), and surfaces the Top 15 newsworthy changes — styled as a monochrome editorial newsroom.

**Roster source of truth:** `data/curated_artists.yaml`. The customer-curated list is authoritative; `scripts/build_roster.py` produces `data/roster.json` from it. Web scraping is demoted to an enrichment helper (filling missing social links / images / bios) — it never adds or removes artists.

## Stack

- **Frontend**: React 18 + Vite + Tailwind CSS
- **Scraping**: Python 3.12 (requests, BeautifulSoup4, lxml)
- **Data**: JSON snapshots in `data/` → SQLite for history → optional Cloud Firestore
- **AI editorial**: Anthropic API (claude-sonnet-4-20250514) for news blurbs
- **Deployment**: GCP Cloud Storage (static) or Cloud Run
- **Scheduling**: cron or GCP Cloud Scheduler for daily refresh

## Commands

- `npm run dev` — Start Vite dev server (frontend)
- `npm run build` — Production build to `dist/`
- `npm run preview` — Preview production build locally
- `npm run lint` — ESLint + Prettier check
- `npm run test` — Vitest (unit + component tests)
- `python scripts/build_roster.py` — Build `data/roster.json` from `data/curated_artists.yaml` (Phase 1)
- `python scripts/scrape_roster.py` — (legacy / discovery only) scrape sonymusiclatin.com to find new artists
- `python scripts/harvest_social.py` — Pull social media metrics for all artists
- `python scripts/compute_kpis.py` — Calculate KPIs and deltas against last snapshot
- `python scripts/generate_news.py` — Score changes and produce Top 15 briefing
- `python scripts/run_pipeline.py` — Full daily pipeline (build → harvest → KPIs → news → export)
- `pip install -r requirements.txt` — Install Python dependencies

## Key Directories

- `src/` — React frontend source
- `src/components/` — UI components (ArtistCard, NewsItem, KPILeaderboard, etc.)
- `src/data/` — TypeScript types and data loaders
- `scripts/` — Python pipeline scripts (scraping, harvesting, KPI computation)
- `data/snapshots/` — Daily JSON snapshots (`YYYY-MM-DD.json`)
- `data/images/` — Artist headshot images (named `{artist-slug}.jpg`)
- `data/curated_artists.yaml` — **Source of truth** for which artists the pipeline tracks (hand-edited)
- `data/roster.json` — Generated from `curated_artists.yaml` by `build_roster.py`; consumed by all downstream phases and the frontend
- `skill/` — The SKILL.md and reference docs (read-only knowledge base)
- `public/` — Static assets served by Vite

## Architecture

The app has two distinct halves that run independently:

**Data pipeline** (Python, runs daily via cron):
`build_roster (curated YAML → roster.json) → harvest_social → compute_kpis → generate_news → write JSON to data/`

**Frontend** (React, reads JSON at build or runtime):
`load JSON → render dashboard → no API calls at runtime (fully static after build)`

The pipeline writes JSON files that the frontend consumes. There is no backend server.
For the AI editorial blurbs, the pipeline calls the Anthropic API during `generate_news`
and bakes the results into the JSON — the frontend never calls an LLM.

## Design System — STRICTLY MONOCHROME

This is not a suggestion. The entire UI is black, white, and shades of gray. No color anywhere — not in charts, not in badges, not in hover states. The only "color" moment is artist headshots revealing from grayscale to full color on hover.

```
--bg-primary: #0A0A0A
--bg-card: #1A1A1A
--text-primary: #FFFFFF
--text-secondary: #999999
--border: #2A2A2A
```

Use font weight, size, spacing, and opacity to create hierarchy — never hue.

## Typography

- Headlines: `Playfair Display` (weight 900, serif)
- Data/KPIs: `IBM Plex Mono` (monospace, for all numbers)
- UI labels: `DM Sans` or similar grotesque sans-serif (weight 500)
- Import all from Google Fonts in `index.html`

## Artist Images

All artist headshots render as circles (`border-radius: 50%`; `object-fit: cover`).
Apply `filter: grayscale(100%)` by default. Transition to `grayscale(0%)` on hover.
Store originals in `data/images/{slug}.jpg` at 400×400 minimum.

## Coding Conventions

- TypeScript strict mode — no `any`, use `unknown` and narrow
- Functional components only, hooks for state
- Named exports, no default exports (except page-level route components)
- Tailwind utility classes, no inline styles, no CSS modules
- Python scripts use type hints, f-strings, pathlib for file paths
- All data files are JSON with ISO 8601 dates
- Snake_case for Python, camelCase for TypeScript, kebab-case for file names

## Scraping Gotchas

- `sonymusiclatin.com` returns **403** on direct fetch — always try, but fall back to web search + Wikipedia roster list when blocked
- The paginated roster URL is `/artist/page/{N}/` (note: `/artist/` singular, NOT `/artists/`)
- Social links may only appear on individual artist detail pages, not on the grid cards
- Instagram and TikTok profiles are JS-rendered — use Social Blade or search aggregators instead of direct scraping
- Spotify artist pages (`open.spotify.com/artist/{id}`) do expose monthly listeners in the HTML
- Always timestamp every data point with `data_freshness` so the frontend can show staleness

## KPI Reference

There are exactly 11 KPIs. Read `skill/references/kpi-formulas.md` for full calculation details.
The short list: Total Social Reach, Reach Velocity, Engagement Rate, Spotify Monthly Listeners,
Spotify Listener Trend, Content Velocity, Platform Diversity Score, YouTube Weekly Velocity,
Latest Release Recency, News & Press Mentions, Apple Music Catalog Activity.

## News Scoring Reference

Read `skill/references/news-scoring.md` for the weighted rubric. The Top 15 are selected
by score descending, ties broken by artist reach tier then recency.

## Curated Roster Maintenance

The pipeline tracks **only** artists listed in `data/curated_artists.yaml`. To add, remove, or edit an artist:

1. Edit `data/curated_artists.yaml` (append a block, delete one, or change fields).
2. Run `python scripts/build_roster.py` (or just `npm run pipeline` for the full daily run).
3. Commit the YAML change.

**Slug stability is critical.** The `slug` field is the immutable key across `data/snapshots/`, `data/images/`, and frontend routing. Never change a slug for an existing artist — rename the display `name` instead. If a slug truly must change, also rename the corresponding files in `data/snapshots/` and `data/images/` so historical KPI data isn't orphaned.

**Status lifecycle:**
- `active` — fully tracked across all 11 KPIs and all news signals
- `hiatus` — tracked, but expect quiet periods; news scoring damps "platform silence" alerts
- `legacy_estate` — deceased artist or sunset project; KPIs 2/3/6/7 (velocity, engagement, content, diversity) are nulled out and live-activity news signals are suppressed. Catalog signals (milestones, Spotify trend, new release, press) still fire.
- `archived` — kept in YAML for history; pipeline ignores. Use this instead of deletion when you want to preserve historical snapshots/news.

**Schema reference:** see `skill/references/curated-artists.md`.

## Avoid

- No color in the UI — this is a monochrome design, period
- No `localStorage` or `sessionStorage` — data comes from JSON files
- No runtime API calls from the frontend — everything is pre-baked by the pipeline
- No scraping Instagram/TikTok directly — they block; use aggregator sites
- No fabricating social links or metrics — mark missing data as `null` with a reason
- No barrel files (`index.ts` re-exports) — import directly from source modules

## Environment Variables

```env
# Required for AI editorial blurbs
ANTHROPIC_API_KEY=sk-ant-...

# Optional — for enhanced Spotify data
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=

# Optional — for YouTube video stats
YOUTUBE_API_KEY=

# Deployment
GCP_PROJECT_ID=
GCP_BUCKET_NAME=
```

## Progressive Disclosure

For deeper context on any topic, read the reference files:
- @./skill/SKILL.md — Full skill definition with all 5 pipeline phases
- @./skill/references/kpi-formulas.md — KPI calculations, tiers, alert thresholds
- @./skill/references/news-scoring.md — Newsworthiness matrix and editorial templates
- @./skill/references/scraping-strategy.md — Platform-specific scraping fallbacks
