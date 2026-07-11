# sme_artistTracker — Technical Specification

> **Purpose of this document.** Complete, self-contained specification for the
> Sony Music Entertainment regional artist intelligence dashboard. A
> development team given **only** this document (without access to the existing
> codebase) should be able to reimplement the system end-to-end. Every formula,
> URL pattern, schema, design token, and gotcha that would otherwise require
> archaeology is captured here.
>
> Intended use: hand to a build team, or point Claude Code / similar AI tools
> at this file as the source of truth.
>
> **Status:** Reflects the system as built through 2026-05-27.

---

## 1. Executive summary

`sme_artistTracker` is a daily-refresh web application that tracks a
**customer-curated roster of regional Latin and Lusophone music artists**
across Sony Music Entertainment's divisions (Sony Music Latin, Sony Music
Brasil, Sony Music Spain, Sony Music Mexico) plus select non-Sony artists of
strategic interest. The application has two halves that run independently:

1. **A daily data pipeline** (Python) that harvests publicly available metrics
   from social media, streaming, video, and press sources, computes **11 KPIs**
   per artist with day-over-day deltas, scores significant changes against a
   weighted rubric, and produces a **Top 15 newsworthy briefing** with editorial
   blurbs written by an LLM.

2. **A static React dashboard** (Vite + Tailwind) that consumes the pipeline's
   JSON output at build time and renders it as a monochrome editorial
   newsroom — masthead, news ticker, story feed, artist grid, KPI
   leaderboards, and an AI analyst chat surface.

The system is **fully static after build** — no backend server, no runtime
API calls from the frontend. Deployable to any static host (GCS, Cloudflare
Pages, S3, etc.). Designed to run on a single developer machine via launchd at
06:00 daily, or in a container in production.

### Top-line numbers (target)

| Metric | Value |
|---|---|
| Artists tracked | 46 (customer-curated; designed to scale to ~500 without architectural changes) |
| KPIs per artist | 11 |
| News items per day | Top 15 by weighted score |
| Platforms harvested per artist | 8 (Spotify, Instagram, YouTube, TikTok, X/Twitter, Facebook, Apple Music, Google News) |
| Pipeline runtime | ~14 minutes wall clock |
| Frontend bundle | ~3 MB raw / ~430 KB gzip |
| Tech debt risk | Bundle growth from data baking; switch to runtime fetch above ~5 MB raw |

---

## 2. Scope and stakeholders

**Primary user:** Sony Music Entertainment artist intelligence / A&R staff
looking for a daily executive briefing on the regional roster.

**Customer profile:** Reviews the dashboard daily; provides the curated artist
list and periodic updates (additions, removals, social URL corrections);
reviews KPI definitions for relevance.

**Project sponsor / maintainer:** Chromadata (development partner). Operates
the daily pipeline, deploys updates, integrates client feedback.

**Out of scope:**

- Authentication / user accounts / personalization (the dashboard is shared and
  static).
- Real-time push notifications (the pipeline is daily; news items are not
  intraday).
- Modifying or transacting against artist accounts (read-only intelligence).
- Direct integration with Sony Music's internal systems (this is an external
  intelligence layer that reads public data).

---

## 3. Architecture overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ROSTER MANAGEMENT (hand-curated)                                          │
│                                                                            │
│   data/curated_artists.yaml  ◄── customer-curated, edited by maintainer    │
│   data/curated_social_links_filled.csv  ◄── periodic client returns         │
│                       │                                                    │
│                       │   scripts/merge_social_links.py                    │
│                       ▼                                                    │
│              data/curated_artists.yaml                                     │
└────────────────────────────────┬──────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────────────┐
│ DAILY PIPELINE (run by launchd at 06:00, or `npm run build:full` manually) │
│                                                                            │
│   Phase 1   build_roster.py     YAML → data/roster.json                    │
│   Phase 1b  enrich_links.py     MusicBrainz fills missing socials          │
│   Phase 1c  fetch_images.py     Spotify og:image → Deezer → Wikipedia      │
│   Phase 2   harvest_social.py   Per-artist metrics (8 platforms)           │
│             + harvest_kworb.py  Spotify per-track streams                  │
│             + harvest_itunes.py iTunes Search API (Apple Music)            │
│   Phase 3   compute_kpis.py     11 KPIs + deltas vs prior snapshot         │
│   Phase 4   generate_news.py    Signal scoring + LLM editorial blurbs      │
│                       │                                                    │
│                       ▼                                                    │
│              data/snapshot.json, data/news.json, data/dashboard.json       │
└────────────────────────────────┬──────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────────────┐
│ FRONTEND BUILD (`npm run build`)                                           │
│                                                                            │
│   src/data/loader.ts  imports JSON files via Vite's import.meta.glob       │
│   Vite + Tailwind     produces dist/ (static)                              │
│                       │                                                    │
│                       ▼                                                    │
│                       dist/                                                │
└────────────────────────────────┬──────────────────────────────────────────┘
                                 │
                                 ▼
                  Deploy to GCS / static host
```

**Key architectural decisions:**

| Decision | Rationale |
|----------|-----------|
| Curated YAML drives the roster (not a scrape) | Customer review found the Wikipedia-scraped Sony Music Latin roster was missing strategically important Brazilian artists, Spanish artists, and non-Sony tracking targets. The customer maintains the canonical list. |
| Scraper demoted to enrichment helper | `scripts/scrape_roster.py` is kept as a discovery tool (to find new SML signings the curated list might miss) but not in the daily pipeline. |
| Static frontend, JSON-at-build-time | Simpler, cheaper, deployable anywhere. Trade-off: bundle grows with data; switch to runtime fetch above ~5 MB. |
| Anthropic API called only at pipeline time | Frontend never makes API calls; editorial blurbs are baked in. Cost-bounded; no rate limits at runtime. |
| iTunes Search API for Apple Music data | Apple Music web pages are JS-rendered and resist scraping. iTunes Search is a free public JSON endpoint covering catalog, releases, top songs, genre. |
| kworb.net for Spotify per-track streams | Static HTML pages; per-artist Spotify IDs map to `kworb.net/spotify/artist/{id}.html`. kworb's YouTube section does NOT have per-artist pages — YouTube data comes from parsing the channel `/videos` page directly. |
| YouTube via lockupViewModel parsing | YouTube migrated the videos grid to `lockupViewModel` blocks embedded in the page's JS state. Recognizing this format (vs. the legacy `videoRenderer`) is critical and depends on User-Agent. |
| All comments, all formulas, all gotchas in docs | This document is the source of truth for redevelopment. |

---

## 4. Tech stack

### Backend / pipeline

- **Python 3.12+** (uses `from __future__ import annotations`, type hints)
- **`requests`** — minimal use; primary HTTP path is `curl` via `subprocess`
- **`beautifulsoup4`** with `html.parser` (no lxml dep required, but lxml is a
  faster optional parser)
- **`PyYAML 6.0.2`** — `data/curated_artists.yaml` parsing
- **`ruamel.yaml 0.18.6`** — comment-preserving YAML writer used by
  `scripts/merge_social_links.py`
- **`anthropic 0.49.0`** — Claude API for editorial blurbs in Phase 4
- **`curl`** binary — primary HTTP client; chosen over Python's `requests`
  because curl is more reliable through macOS/Linux network sandboxing and
  handles compressed responses cleanly. Each fetch has a `--max-time` cap.

### Frontend

- **React 19** functional components + hooks (no class components, no Redux,
  no Context API)
- **Vite 8** — dev server (HMR), production build
- **TypeScript 6** — strict mode; `any` is forbidden, use `unknown` and narrow
- **Tailwind CSS 4** — utility classes via `@tailwindcss/vite` plugin
- **No barrel files** — import directly from source modules
- **Named exports only** (except route-level components)

### Deployment

- **GCP Cloud Storage** static hosting (primary)
- **Cloud Run** (alternative — for cases where dynamic SSR is wanted later)
- Deploy script: `scripts/deploy-gcs.sh`

### Scheduling

- **launchd** on macOS (production) — see `infra/launchd/com.chromadata.smetracker.plist`
- Daily at 06:00 local time
- Wrapper script: `scripts/cron_refresh.sh` handles env loading, logging,
  notifications

### Notifications

- **Python `smtplib`** — generic SMTP, configured via env vars
- Falls back to `logs/notifications.log` if SMTP isn't configured (pipeline never blocks on email failure)

---

## 5. Repository layout

```
sme_artistTracker/
├── CLAUDE.md                          # Project orientation for Claude Code (concise)
├── README.md                          # Surface-level intro
├── docs/
│   └── TECHNICAL_SPEC.md              # ← this document
├── data/
│   ├── curated_artists.yaml           # AUTHORITATIVE roster — hand-edited
│   ├── curated_social_links_template.csv     # Blank template sent to client
│   ├── curated_social_links_filled.csv       # Client returns this
│   ├── roster.json                    # Generated by build_roster.py
│   ├── snapshot.json                  # Generated by compute_kpis.py (frontend)
│   ├── dashboard.json                 # Generated by compute_kpis.py (rich)
│   ├── news.json                      # Generated by generate_news.py (frontend)
│   ├── snapshots/
│   │   ├── YYYY-MM-DD.json            # Harvest output (raw per-platform data)
│   │   └── YYYY-MM-DD-kpis.json       # KPI snapshot (computed metrics)
│   ├── news/
│   │   └── YYYY-MM-DD.json            # Daily news briefing archive
│   └── images/
│       └── {artist-slug}.jpg          # Local artist headshots
├── scripts/
│   ├── build_roster.py                # Phase 1: YAML → roster.json
│   ├── enrich_links.py                # Phase 1b: MusicBrainz social links
│   ├── fetch_images.py                # Phase 1c: image discovery
│   ├── harvest_social.py              # Phase 2: per-platform metrics
│   ├── harvest_kworb.py               # Phase 2 helper: kworb Spotify
│   ├── harvest_itunes.py              # Phase 2 helper: iTunes Search API
│   ├── compute_kpis.py                # Phase 3: 11 KPIs + deltas
│   ├── generate_news.py               # Phase 4: signal scoring + LLM blurbs
│   ├── run_pipeline.py                # Orchestrator — phases 1-4 in sequence
│   ├── merge_social_links.py          # Tool: merge client CSV into YAML
│   ├── scrape_roster.py               # Legacy discovery tool (SML / Wikipedia)
│   ├── cron_refresh.sh                # Production wrapper for launchd
│   ├── notify.py                      # Email notification helper
│   ├── deploy-gcs.sh                  # Deploy dist/ to GCS bucket
│   └── deploy.py                      # Alternative deployment (Cloud Run)
├── infra/
│   └── launchd/
│       └── com.chromadata.smetracker.plist   # launchd schedule for 06:00 daily
├── logs/
│   ├── pipeline-YYYY-MM-DD.log        # Dated pipeline run logs (rotated 30d)
│   ├── launchd.out / launchd.err      # launchd-level stdio
│   └── notifications.log              # Fallback when SMTP not configured
├── skill/
│   ├── SKILL.md                       # Original concept doc
│   └── references/
│       ├── kpi-formulas.md            # KPI formulas (overlap with §7 here)
│       ├── news-scoring.md            # News scoring (overlap with §8 here)
│       ├── scraping-strategy.md       # Per-platform notes
│       └── curated-artists.md         # YAML schema + lifecycle
├── src/                               # React frontend
│   ├── App.tsx                        # Root component, tab nav, page sections
│   ├── main.tsx                       # ReactDOM entry
│   ├── index.css                      # Tailwind + design tokens
│   ├── components/
│   │   ├── artist-card.tsx
│   │   ├── kpi-leaderboard.tsx
│   │   ├── news-item.tsx
│   │   ├── chat-agent.tsx
│   │   ├── analyst-page.tsx
│   │   └── sml-logo.tsx
│   ├── data/
│   │   ├── loader.ts                  # Imports JSON via Vite glob
│   │   └── types.ts                   # TypeScript types for all schemas
│   └── lib/
│       └── ai-utils.ts
├── public/                            # Static assets served by Vite
├── dist/                              # Production build output (gitignored)
├── .venv/                             # Python virtual env (gitignored)
├── node_modules/                      # JS deps (gitignored)
├── requirements.txt
├── package.json
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── vite.config.ts
├── firebase.json
├── index.html
└── .env.example                       # Template for .env (gitignored)
```

---

## 6. Core schemas

All schemas use JSON unless noted. Dates are ISO 8601 (`YYYY-MM-DD`).

### 6.1 `data/curated_artists.yaml` (the authoritative roster)

```yaml
version: "1.0"
updated: "YYYY-MM-DD"
maintainer: "email@chromadata.com"
source: "Customer-provided curated list, YYYY-MM-DD"

artists:
  - name: "Display Name"                # required, used in UI
    slug: "url-safe-slug"               # required, IMMUTABLE key
    aliases: ["Alt Name"]               # optional, helps match legacy data
    country: "ISO-2"                    # optional, e.g. AR, BR, ES, MX, US
    primary_market: "free text"         # optional
    genre_tags: [pop, urbano]           # optional, lower-case kebab
    label_division: "free text"         # optional, e.g. "Sony Music Brasil"
    label_status:                       # optional, allowed values:
      # sony-latin | sony-brasil | sony-spain | sony-mexico | non-sony | unconfirmed
    entity_type:                        # optional, allowed values:
      # solo | duo | group | estate
    members:                            # required when duo/group; optional otherwise
      - { name: "Member", slug: "member-slug" }
    status:                             # optional, allowed values:
      # active | hiatus | legacy_estate | archived
    deceased_date: "YYYY-MM-DD"         # required when status=legacy_estate
    priority:                           # optional, allowed values:
      # high | standard | rising | catalog
    social_links:                       # optional manual overrides (wins over scraper)
      instagram: "https://..."
      youtube:   "https://..."
      tiktok:    "https://..."
      x:         "https://..."
      spotify:   "https://..."
      apple_music: "https://..."
      facebook:  "https://..."
      soundcloud: "https://..."         # rarely used
    image_url: "https://..."            # optional manual override
    bio_excerpt: "..."                  # optional manual override
    notes: "free text"                  # optional, for maintainers
```

**Validation rules** (enforced by `build_roster.py` at load):

- `name` and `slug` are present and non-empty
- `slug` values are unique across the file
- All enum fields use allowed values
- `slug` is lowercase ASCII + hyphens + digits (validated implicitly downstream)

**Slug stability:** Slugs are the immutable key across `data/snapshots/`,
`data/images/`, and frontend routing. NEVER change a slug for an existing
artist; rename the display `name` instead. If a slug truly must change, also
rename the corresponding files in `data/snapshots/` and `data/images/`.

### 6.2 `data/roster.json`

Generated from the YAML by `build_roster.py`. Read by every downstream
consumer.

```json
{
  "roster_date":  "YYYY-MM-DD",
  "source":       "curated:curated_artists.yaml (v1.0)",
  "artist_count": 46,
  "artists": [
    {
      "name":             "Display Name",
      "slug":             "url-safe-slug",
      "profile_url":      "https://www.sonymusiclatin.com/artists/...",
      "image_url":        "https://i.scdn.co/image/...",
      "image_local_path": "data/images/{slug}.jpg",
      "bio_excerpt":      "...",
      "social_links": {
        "instagram":   "https://..." | null,
        "youtube":     "https://..." | null,
        "tiktok":      "https://..." | null,
        "x":           "https://..." | null,
        "spotify":     "https://..." | null,
        "apple_music": "https://..." | null,
        "facebook":    "https://..." | null,
        "soundcloud":  "https://..." | null
      },
      "country":        "ISO-2",
      "genre_tags":     [...],
      "label_division": "...",
      "label_status":   "sony-latin",
      "entity_type":    "solo",
      "members":        [{ "name": "...", "slug": "..." }],
      "status":         "active",
      "deceased_date":  "YYYY-MM-DD",
      "priority":       "high",
      "aliases":        ["..."],
      "notes":          "..."
    }
  ]
}
```

### 6.3 `data/snapshots/YYYY-MM-DD.json` (raw harvest)

```json
{
  "harvest_date": "YYYY-MM-DD",
  "artists": [
    {
      "artist_slug": "...",
      "artist_name": "...",
      "harvest_date": "YYYY-MM-DD",
      "platforms": {
        "spotify": {
          "monthly_listeners": int | null,
          "top_tracks":        [...],
          "latest_release":    { "title": str, "date": str },
          "kworb_top_tracks":  [{ "title": str, "streams": int, "peak_date": str }],
          "kworb_total_streams": int | null,
          "profile_url":       str,
          "data_source":       "spotify_page",
          "data_freshness":    "YYYY-MM-DD",
          "fetch_status":      "ok" | "error" | "no_url" | ...
        },
        "instagram": { "followers": int | null, "posts_count": int | null,
                       "recent_posts": [...], ... },
        "youtube": {
          "subscribers": int | null,
          "recent_videos": [
            { "video_id": str, "title": str, "views": int | null,
              "published_date": str | null }
          ],
          "data_source": "youtube_page",
          ...
        },
        "tiktok":    { "followers", "likes_total", "recent_videos", ... },
        "x":         { "followers", "recent_tweets", ... },
        "facebook":  { "page_likes", "followers", ... },
        "apple_music": {                          // From iTunes Search API
          "artist_id":            int,
          "primary_genre":        str,
          "latest_release":       { "title", "date", "type" },
          "recent_releases_90d":  int,
          "total_albums":         int,
          "top_songs":            [{ "title", "album", "release_date" }],
          "profile_url":          str,
          "data_source":          "itunes_search_api",
          "fetch_status":         "ok" | "no_match" | "error"
        }
      },
      "press_mentions": {
        "count":     int,
        "headlines": [...],
        "source":    "google_news_rss",
        "fetch_status": "ok" | "blocked" | "error"
      }
    }
  ]
}
```

### 6.4 `data/snapshots/YYYY-MM-DD-kpis.json` (computed KPIs)

```json
{
  "snapshot_date":          "YYYY-MM-DD",
  "previous_snapshot_date": "YYYY-MM-DD",
  "generated_at":           "YYYY-MM-DDTHH:MM:SS+00:00",
  "artist_count":           46,
  "artists": [
    {
      "artist_slug":  "...",
      "artist_name":  "...",
      "tier":         "mega" | "major" | "rising" | "emerging",
      "image_url":    "...",
      "image_local":  "...",
      "profile_url":  "...",
      "social_links": { ... },
      "country":      "ISO-2",
      "label_status": "sony-latin",
      "status":       "active",
      "priority":     "high",
      "genre_tags":   [...],
      "snapshot_date": "YYYY-MM-DD",
      "kpis": [
        {
          "kpi_id":         1,
          "kpi_name":       "Total Social Reach",
          "unit":           "followers",
          "current_value":  number | null,
          "previous_value": number | null,
          "delta_absolute": number | null,
          "delta_percent":  number | null,
          "trend":          "up" | "down" | "flat" | "unknown",
          "benchmark_tier": string | null,
          "alert":          string | null,
          // KPI-specific extra fields (e.g. headlines for KPI 10, top_songs for KPI 11)
          "...":            "..."
        }
      ]
    }
  ]
}
```

### 6.5 `data/news/YYYY-MM-DD.json` (editorial briefing)

```json
{
  "news_date":       "YYYY-MM-DD",
  "source_snapshot": "data/snapshots/YYYY-MM-DD-kpis.json",
  "items": [
    {
      "priority":        1,
      "score":           15.0,
      "signal_type":     "milestone" | "new_release" | "viral_spike" | ...,
      "headline":        "Becky G crosses 40M Instagram followers",
      "artist_name":     "...",
      "artist_slug":     "...",
      "artist_tier":     "mega",
      "image_url":       "...",
      "kpi_impact": [
        { "kpi_id": 1, "kpi_name": "Total Social Reach",
          "delta_absolute": 1200000, "delta_percent": 3.1,
          "current_value": 40000000, "direction": "up",
          "benchmark_tier": "mega" }
      ],
      "summary":         "2-3 sentence editorial blurb...",
      "source":          "Spotify direct fetch",
      "data_confidence": "verified" | "recent" | "estimated" | "stale" | "inferred",
      "timestamp":       "ISO-8601"
    }
  ]
}
```

### 6.6 `data/snapshot.json` and `data/news.json` (frontend aliases)

Identical to the latest dated KPI snapshot and news briefing respectively.
Written by `compute_kpis.py` and `generate_news.py` at the end of each run.
Imported by `src/data/loader.ts` at frontend build time.

---

## 7. The 11 KPIs

### 7.1 Quick reference

| # | Name | Unit | Higher better? | Source platforms |
|--:|------|------|:--:|------|
| 1 | Total Social Reach | followers | ✓ | All 6 social + Spotify |
| 2 | Social Reach Velocity | % | ✓ | KPI 1 day-over-day |
| 3 | Engagement Rate | % | ✓ | Recent posts × KPI 1 |
| 4 | Spotify Monthly Listeners | listeners | ✓ | Spotify |
| 5 | Spotify Listener Trend | % | ✓ | KPI 4 day-over-day |
| 6 | Content Velocity | posts/wk | ✓ | All platforms (7-day window) |
| 7 | Platform Diversity Score | ratio | ✓ | Account presence audit |
| 8 | YouTube Weekly Velocity | views/wk | ✓ | YouTube recent videos |
| 9 | Latest Release Recency | days | ✗ | Spotify + Apple Music (max date) |
| 10 | News & Press Mentions | articles | ✓ | Google News RSS, 7-day window |
| 11 | Apple Music Catalog Activity | releases/90d | ✓ | iTunes Search API |

### 7.2 Formulas

**KPI 1 — Total Social Reach**

```
total_reach = instagram.followers + youtube.subscribers + tiktok.followers
            + x.followers + facebook.page_likes + spotify.monthly_listeners
```

Tier benchmarks:

- mega: > 50,000,000
- major: 10M–50M
- rising: 1M–10M
- emerging: < 1M

Missing platform values are treated as 0 (an artist with no TikTok still
contributes their Spotify count).

**KPI 2 — Social Reach Velocity**

```
velocity = ((current_reach - previous_reach) / previous_reach) * 100
```

Alert thresholds:

- "Breakout": > 5% daily
- "Strong": 2–5% daily
- "Steady": ±1% daily
- "Declining": < -1% daily
- "Freefall": < -5% daily

**KPI 3 — Engagement Rate**

```
total_engagement = sum(likes + comments) across last 10 posts (all platforms)
engagement_rate  = (total_engagement / total_reach) * 100
```

Benchmarks (music industry):

- Excellent: > 3.5%
- Good: 1.5–3.5%
- Average: 0.5–1.5%
- Low: < 0.5%

**KPI 4 — Spotify Monthly Listeners**

Direct value from Spotify artist page. Tier benchmarks:

- Global Star: > 50M
- Regional Power: 20M–50M
- Strong: 5M–20M
- Growing: 1M–5M
- Niche: < 1M

**KPI 5 — Spotify Listener Trend**

```
trend = ((current_listeners - previous_listeners) / previous_listeners) * 100
```

Context: a new release typically spikes 20–100% then normalizes over 4–6 weeks.

**KPI 6 — Content Velocity**

```
content_velocity = count(posts published in last 7 days across all platforms)
```

Benchmarks:

- Hyperactive: > 14 / week
- Active: 7–14
- Moderate: 3–7
- Low: 1–3
- Silent: 0

**KPI 7 — Platform Diversity Score**

```
active_platforms = count(platforms with non-null URL in roster.json social_links
                          AND a post/release in last 30 days, OR fallback to
                          presence-only when last-post data unavailable)
total_platforms  = count(platforms where artist has any URL)
diversity_score  = active_platforms / total_platforms
```

Risk assessment:

- 1.0: Fully diversified
- 0.7–0.99: Healthy
- 0.5–0.69: Some gaps
- < 0.5: Platform dependency risk

**KPI 8 — YouTube Weekly Velocity**

```
recent_videos = 5 most recent YouTube videos
                (parsed from /videos page lockupViewModel; see §11.3)
velocity     = average(views across recent_videos)
```

Renamed from "Video View Momentum" in May 2026. Falls back to TikTok recent
video views if the artist has no YouTube channel.

**KPI 9 — Latest Release Recency**

```
spotify_date  = sp.latest_release.date         (from Spotify page)
apple_date    = am.latest_release.date         (from iTunes Search API)
release_date  = max(spotify_date, apple_date)  # most recent wins
recency_days  = today - release_date
```

The `extra` payload carries `release_source` (`spotify` | `apple_music`) so the
frontend can show provenance.

Flags:

- Fresh: 0–14 days
- Recent: 15–60 days
- Aging: 61–120 days
- Overdue: 121–180 days
- Dark: > 180 days (flag to A&R)

**KPI 10 — News & Press Mentions**

```
mentions = count(unique articles mentioning artist in last 7 days)
```

Source: Google News RSS (`news.google.com/rss/search?q=...&tbs=qdr:w`).

Benchmarks:

- Trending: > 20 / week
- Visible: 10–20
- Moderate: 5–10
- Quiet: 1–5
- Off-radar: 0

**KPI 11 — Apple Music Catalog Activity**

```
recent_releases_90d = count(album/EP/single on iTunes Search API
                            with releaseDate within last 90 days)
```

Source: `itunes.apple.com/lookup?id={artistId}&entity=album&sort=recent`.

Tiers:

- Hyperactive: 5+
- Active: 3–4
- Moderate: 1–2
- Dormant: 0

`extra` carries `total_albums`, `top_songs`, `latest_release`, `primary_genre`
for display purposes.

### 7.3 Delta tracking (every KPI)

For each KPI on each artist:

```json
{
  "current_value":  ...,
  "previous_value": ...,
  "delta_absolute": current - previous,
  "delta_percent":  (current - previous) / previous * 100,
  "trend":          "up" if delta_percent > 1
                    "down" if delta_percent < -1
                    "flat" otherwise
                    "unknown" if either value missing
}
```

### 7.4 Status-aware KPI gating

Artists with `status: legacy_estate` (e.g., Vicente Fernández, d. 2021-12-12)
have no live activity to track. The KPI engine nulls out KPIs 2, 3, 6, 7 and
sets `alert: "legacy_estate"`. Catalog KPIs (1, 4, 5, 8, 9, 10, 11) continue
to compute and remain newsworthy — posthumous releases and catalog momentum
matter.

---

## 8. News scoring

The news desk ranks every detected change across all artists and selects the
**Top 15** by weighted score for the daily briefing.

### 8.1 Signal types and base scores

| Signal | Base score | Trigger |
|--------|-----------:|---------|
| `milestone` | 10 | Round-number follower milestone crossed (10M, 25M, 50M, 100M etc.) |
| `new_release` | 9 | KPI 9 ≤ 14 days |
| `apple_music_surge` | 7 | KPI 11 delta_absolute ≥ 2 OR delta_percent ≥ 100% (current ≥ 2) |
| `spotify_surge` | 8 | KPI 5 > 20% positive change |
| `viral_spike` | 8 | Recent YouTube video views > 5× artist's 30-day average |
| `pr_event` | 7 | KPI 10 > 20 in past 7 days |
| `rapid_follower_surge` | 7 × 1.1^(velocity - 2) | KPI 2 > 2% AND ≤ 1000% (above 1000% is data discontinuity, skipped) |
| `engagement_anomaly` | 7 | KPI 3 shifted > 50% from baseline |
| `platform_silence` | 5 | KPI 6 = 0 |
| `platform_silence_breaking` | 5 | KPI 6 was 0, now > 0 |
| `declining_metrics` | 5 | Sustained drop ≥ 3 consecutive days |
| `video_momentum` | 4 | KPI 8 > 1M views average AND not classified as viral_spike |

### 8.2 Multipliers

- Milestone ×1.5 if round number (10M, 50M, 100M)
- New release ×1.3 if collab with another roster artist (detected via shared
  track title)
- Chart entry ×1.5 if #1 position; ×1.2 if Billboard
- Award ×1.5 if Grammy / Latin Grammy
- Cross-genre collab ×1.2
- Inter-roster collab ×1.3
- Tour ×1.2 if international dates
- Engagement anomaly ×1.2 if sustained > 24 hours
- Platform silence ×1.3 if previously high-frequency poster

### 8.3 Tie-breakers (when score is equal)

1. Artist reach tier (mega > major > rising > emerging)
2. Recency (more recent = higher)
3. Data confidence

### 8.4 Score cap

Final score for any single signal is capped at 15.0. This protects against
runaway exponentials (the `1.1^(velocity-2)` exponent for `rapid_follower_surge`
is itself clamped at `velocity - 2 ≤ 100` as a defensive measure).

### 8.5 Status-aware signal suppression

For artists with `status: legacy_estate`, the following signals are
**suppressed** (would be journalistically false):

- `rapid_follower_surge`
- `video_momentum` / `viral_spike`
- `platform_silence` / `platform_silence_breaking`
- `engagement_anomaly`
- `declining_metrics`

Catalog signals (`milestone`, `spotify_surge`, `new_release`, `pr_event`,
`apple_music_surge`) continue to fire for estates — posthumous releases and
catalog activity are legitimate news.

### 8.6 Editorial blurb generation

The top 15 signals are submitted to the **Anthropic Claude API**
(model: `claude-sonnet-4-20250514` or successor) for editorial blurb
generation. The system prompt frames the model as:

> "A senior music journalist covering Sony Music Entertainment's regional
> Latin and Lusophone roster — spanning Sony Music Latin, Sony Music Brasil,
> Sony Music Spain, plus select non-Sony artists of strategic interest — for
> an internal executive intelligence dashboard. Write with the precision of
> Billboard, the directness of a Reuters wire, and the cultural awareness of
> Rolling Stone."

Each signal is presented with all relevant KPI deltas. The model returns a
2–3 sentence factual blurb per signal, plus a punchy headline.

When `ANTHROPIC_API_KEY` is missing or the user passes `--no-ai`,
template-based fallback content is used (see editorial templates in §8.7).

### 8.7 Editorial templates (used when AI unavailable)

```
MILESTONE
{ARTIST} has crossed {NUMBER} followers on {PLATFORM}, adding {DELTA} in the
past {TIMEFRAME}. This places them {CONTEXT}.

NEW RELEASE
{ARTIST} dropped "{TITLE}" {TODAY/YESTERDAY}, their first release in {DAYS} days.
Early signals show {METRIC}.

VIRAL SPIKE
A {PLATFORM} post by {ARTIST} is outperforming their average by {MULTIPLIER}×,
pulling {ENGAGEMENT} interactions in {TIMEFRAME}.

COLLABORATION
{ARTIST_1} and {ARTIST_2} appear to be teaming up — {EVIDENCE}.

ANOMALY (positive)
{ARTIST}'s engagement rate jumped to {RATE}%, up from a {TIMEFRAME} average
of {AVG}%. The surge coincides with {LIKELY CAUSE}.

ANOMALY (negative)
{ARTIST} has lost {NUMBER} {FOLLOWERS/LISTENERS} on {PLATFORM} over the past
{DAYS} days, a {PERCENT}% decline. {CONTEXT}.

PLATFORM SILENCE
{ARTIST} has not posted on {PLATFORM} in {DAYS} days, breaking a pattern of
{FREQUENCY} posting. Their last post on {DATE} {BRIEF DESCRIPTION}.
```

### 8.8 Data confidence indicators

Each news item carries a confidence badge derived from data freshness and
source type:

- ●●●●● **Verified** — direct from platform, fetched today
- ●●●●○ **Recent** — from aggregator or search, < 48h old
- ●●●○○ **Estimated** — multiple sources averaged, < 7 days old
- ●●○○○ **Stale** — best available data, > 7 days old
- ●○○○○ **Inferred** — derived from indirect signals (e.g., chart position
  implying streams)

---

## 9. Pipeline phases — detailed specs

### 9.1 Phase 1 — `build_roster.py`

**Input:** `data/curated_artists.yaml`, optionally prior `data/roster.json`

**Output:** `data/roster.json`

**Logic:**

1. Load YAML, validate (slugs unique, enums in allowed values).
2. Load prior `roster.json` if it exists; build slug → artist map.
3. For each curated artist, construct a `RosterArtist`:
   - `social_links`: manual YAML wins; otherwise carry forward from prior roster;
     null if neither.
   - `image_url`: same precedence (YAML → prior → placeholder).
   - `bio_excerpt`: same precedence.
4. Optionally run SML detail-page enrichment for Sony Music Latin/Mexico
   artists missing socials (Brazilian/non-Sony artists skip this — they aren't
   on the SML site).
5. Write `data/roster.json` in the exact schema in §6.2.

**Idempotency:** Running on the same YAML produces identical output
(modulo enrichment HTTP variability).

**Validation:**

- `name` and `slug` required, non-empty
- `slug` unique across the YAML
- Enum fields: `label_status`, `entity_type`, `status`, `priority` constrained
  to allowed values
- Fails fast with non-zero exit and a list of all errors

**Schema version:** `version: "1.0"` at the YAML top. Future schema migrations
must bump this and the loader should branch on it.

### 9.2 Phase 1b — `enrich_links.py`

**Input:** `data/roster.json`

**Output:** `data/roster.json` (mutated in place)

**Logic:**

For each artist whose `social_links` contains nulls:

1. Query MusicBrainz: `musicbrainz.org/ws/2/artist?query={name}&fmt=json&limit=3`
2. Match by exact name; collect the `relations` array; pick official URLs by
   `type` (`official homepage`, `instagram`, `youtube`, etc.)
3. Update only fields that were null (don't overwrite YAML or prior values).

**Rate limiting:** MusicBrainz allows 1 req/sec. Built-in 1.1s sleep between
artists.

**Failures non-fatal:** skipped artists keep whatever links they had.

### 9.3 Phase 1c — `fetch_images.py`

**Input:** `data/roster.json`

**Output:** `data/roster.json` updated `image_url`/`image_local_path`; downloaded
JPGs in `data/images/{slug}.jpg`

**Source priority:**

1. **Spotify open-page og:image** (`<meta property="og:image">` on
   `open.spotify.com/artist/{id}`). Returns a 640×640 official Spotify
   headshot. Highest reliability for our roster.
2. **Deezer Search API**: `api.deezer.com/search/artist?q={name}&limit=3`,
   return the top result's `picture_xl` (1000×1000).
3. **Wikipedia REST API**:
   `en.wikipedia.org/api/rest_v1/page/summary/{Name_With_Underscores}`,
   return `originalimage.source` or `thumbnail.source`.

**Idempotency:** Skips any artist whose `data/images/{slug}.jpg` already exists
and is > 1 KB. Use `--force` to override.

**Failure handling:** If all three sources fail, keep the placeholder URL
(`placehold.co/400x400/1A1A1A/999999?text={slug}`). Pipeline doesn't fail.

### 9.4 Phase 2 — `harvest_social.py`

**Input:** `data/roster.json`

**Output:** `data/snapshots/YYYY-MM-DD.json`

**Logic:**

For each artist (sequential, with `--delay` seconds between platforms):

| Platform | Method | Output keys |
|----------|--------|-------------|
| Spotify | `fetch(open.spotify.com/artist/{id})` → parse monthly listeners, top tracks, latest release from HTML | `monthly_listeners, top_tracks, latest_release` |
| Spotify (kworb augment) | `harvest_kworb.py` → kworb.net/spotify/artist/{id}.html | `kworb_top_tracks, kworb_total_streams` (merged into spotify block) |
| Instagram | Aggregator search (Social Blade text snippets) or null | `followers, posts_count` |
| YouTube | `fetch(youtube.com/@handle/videos)` → parse `lockupViewModel` blocks | `subscribers, recent_videos[]` |
| TikTok | Aggregator search or null | `followers, likes_total, recent_videos[]` |
| X / Twitter | Aggregator search or null | `followers, recent_tweets[]` |
| Facebook | `fetch(facebook.com/{handle})` → parse "X people like this" | `page_likes, followers` |
| Apple Music | `harvest_itunes.py` → iTunes Search API | `artist_id, latest_release, recent_releases_90d, total_albums, top_songs, primary_genre` |
| News | Google News RSS `news.google.com/rss/search?q="{name}" music&tbs=qdr:w` → count `<item>` tags, extract first 5 headlines | `count, headlines[]` |

**Per-platform fetch timeout:** 14 seconds via curl `--max-time`.

**Response size cap:** 3 MB per response (truncated, no artist page needs more).

**Checkpoint:** Every 10 artists, the script writes the partial snapshot file.
If the pipeline is killed/restarted, work isn't lost.

**User-Agent:** `"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"` —
deliberately truncated (no Chrome/Safari version suffix) because the full UA
triggers Cloudflare bot detection on Spotify. Different UAs return different
HTML formats; see §11.3 for the YouTube case.

### 9.5 Phase 3 — `compute_kpis.py`

**Input:** today's harvest (`data/snapshots/YYYY-MM-DD.json`),
optionally yesterday's KPI snapshot (for deltas), `data/roster.json`

**Output:**
- `data/snapshots/YYYY-MM-DD-kpis.json` (rich format)
- `data/dashboard.json` (rich, alias)
- `data/snapshot.json` (compact frontend format)

**Logic:**

For each artist, compute the 11 KPIs per §7 formulas, attach delta vs.
previous day, classify benchmark tier, set alerts.

Apply legacy_estate gating (§7.4).

Pass through roster metadata (`country`, `label_status`, `status`, `priority`,
`genre_tags`) into the snapshot so the frontend can filter / badge.

### 9.6 Phase 4 — `generate_news.py`

**Input:** `data/snapshots/YYYY-MM-DD-kpis.json`

**Output:**
- `data/news/YYYY-MM-DD.json` (dated archive)
- `data/news.json` (frontend alias)

**Logic:**

1. For each artist, run all signal detectors (§8.1) → list of signal dicts.
2. Apply legacy_estate suppression (§8.5).
3. Apply multipliers (§8.2). Cap score at 15.
4. Sort by `(score desc, tier_rank desc, total_reach desc)`. Take top 15.
5. Call Anthropic Claude API (one request per signal, in parallel or batched)
   to generate `headline` and `summary`. If the API key is missing or
   `--no-ai`, fall back to templates.
6. Emit JSON in the schema from §6.5.

**Defensive coding:** The `rapid_follower_surge` exponent overflows for
extreme velocities (e.g., when an artist's previous baseline was effectively
zero due to a missing URL, now populated → velocity in the millions of %).
The detector therefore:
- **Skips the signal entirely** when `velocity > 1000` (data discontinuity, not news)
- **Clamps** the exponent at `min(velocity - 2, 100)` as a safety net

### 9.7 `run_pipeline.py` — the orchestrator

Wraps phases 1, 1b, 1c, 2, 3, 4 in sequence with phase result tracking
(timing, status, notes). Flags:

- `--skip-build` / `--skip-enrich` / `--skip-images` / `--skip-harvest` /
  `--skip-kpis` / `--skip-news`
- `--limit N` — phase 2 only first N artists (testing)
- `--delay 1.5` — phase 2 inter-request delay
- `--no-ai` — phase 4 uses templates instead of Anthropic
- `--verbose`

Critical-phase failures (build, harvest, KPIs) exit 1. Non-critical failures
(enrich, images, news) downgrade to a warning and continue with the previous
snapshot.

---

## 10. Frontend

### 10.1 Tab navigation order

Top Stories → Artist Roster → KPI Leaderboards → AI Analyst → Overview.

Default landing tab: **Top Stories** (the daily briefing — what a user wants
to see first). Overview, which is the help / reference page, sits last.

### 10.2 Page sections

**Masthead** — Logo (sml-logo.tsx), date with blinking terminal cursor,
"SONY MUSIC LATIN PULSE" wordmark, "DAILY BRIEFING" centred label, stats bar
(artists, KPI count, alerts, story count, prev snapshot date).

**News ticker** — Full-bleed horizontal scrolling ticker of all 15 headlines.
Always visible across every tab.

**Top Stories** — News feed (one card per story; ranked).

**Artist Roster** — Grid of 46 cards. Each card shows headshot (grayscale by
default; reveals to color on hover), name, tier, top 4 KPIs. Click to expand
all 11 KPIs + Apple Music detail panel (latest release, top 5 songs, genre,
catalog depth).

**Search + Tier filter** — Live-filtered search input to the LEFT of the
tier filter buttons. Search filters by artist name + aliases (case-insensitive
substring match). When the search narrows the grid to a single artist, that
artist's card auto-expands.

**KPI Leaderboards** — Top 5 per KPI in 11 mini-tables. Sort toggle (↓ DESC /
↑ ASC) on each. Each leaderboard has a one-paragraph **business narrative**
explaining what the metric means for A&R / commercial decisions.

**AI Analyst** — Chat interface that calls Anthropic Claude with a built
system prompt containing the full roster, current snapshot, and briefing. The
user can ask free-form questions. Suggested questions in a sidebar; clicking
one routes the question into the chat.

**Footer** — Last refresh date, data sources, version, Chromadata attribution.

### 10.3 Component contract

Each component receives data from `src/data/loader.ts` (which imports JSON
via `import.meta.glob` so Vite bundles them at build time). No runtime
fetching.

```typescript
// src/data/loader.ts
export const roster:   Roster;
export const snapshot: Snapshot;
export const briefing: NewsBriefing;
```

These are module-level constants. Re-renders happen only when component state
changes (search input, tier filter, expanded card, sort direction, etc.).

### 10.4 Auto-expand mechanism

`ArtistCard` takes an optional `initiallyExpanded?: boolean` prop. A `useEffect`
syncs the local `expanded` state with that prop:

```tsx
useEffect(() => { setExpanded(initiallyExpanded); }, [initiallyExpanded]);
```

So when the search narrows the grid to one match, the parent passes
`initiallyExpanded={true}` and the card opens. The user can still toggle
expand/collapse manually between prop changes.

---

## 11. Design system

### 11.1 Strictly monochrome — no exceptions in the UI chrome

The entire UI is built from black, white, and shades of gray. **No color
anywhere** in chrome, charts, badges, or hover states. The single exception:
the **artist headshots reveal from grayscale to full color on hover** — that's
the only color moment in the app.

Tab navigation does use distinct accent colors (violet/pink/blue/amber/green)
for the five tabs — this is an exception to the chrome rule, deliberately
scoped, to help orientation when scrolling.

### 11.2 Color tokens (`src/index.css`)

```css
:root {
  --bg-primary:        #0A0A0A;
  --bg-secondary:      #141414;
  --bg-card:           #1A1A1A;
  --bg-card-hover:     #222222;
  --text-primary:      #FFFFFF;
  --text-secondary:    #999999;
  --text-muted:        #666666;
  --border:            #2A2A2A;
  --border-light:      #333333;
  --accent-up:         #FFFFFF;   /* trend up */
  --accent-down:       #666666;   /* trend down */
  --accent-highlight:  #E0E0E0;
}
```

### 11.3 Typography

- **Headlines:** `Playfair Display`, weight 900, serif. Imported from Google Fonts.
- **Data / KPIs:** `IBM Plex Mono`, monospace. For all numeric content.
- **UI labels:** `Inter` (or DM Sans alt), weight 500, grotesque sans-serif.
- Imports declared in `index.html` `<head>`.

### 11.4 Artist images

CSS contract for every artist image instance:

```css
.artist-avatar {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--border-light);
  filter: grayscale(100%);
  transition: filter 0.3s ease;
}
.artist-avatar:hover {
  filter: grayscale(0%);
}
```

Stored locally at `data/images/{slug}.jpg`, served by Vite from `data/` via
relative imports.

### 11.5 KPI color (leaderboard accents only)

The KPI leaderboard tiles use a thin colored top border to differentiate
metrics at a glance. Within each tile, all chrome is monochrome.

```typescript
const KPI_COLOR = {
  1:  '#60a5fa',  // blue
  2:  '#60a5fa',  // blue
  3:  '#c084fc',  // purple
  4:  '#4ade80',  // green
  5:  '#4ade80',  // green
  6:  '#22d3ee',  // cyan
  7:  '#2dd4bf',  // teal
  8:  '#f472b6',  // pink
  9:  '#fbbf24',  // amber
  10: '#fb923c',  // orange
  11: '#f87171',  // rose
};
```

---

## 12. External data sources — detailed

### 12.1 Spotify (open.spotify.com)

**URL pattern:** `https://open.spotify.com/artist/{22-char-id}`

**Method:** HTTP fetch via curl. Parse HTML.

**Extracted fields:**
- Monthly listeners: regex match on `(\d[\d,]+) monthly listeners`
- Top tracks: parse `<script>` JSON-LD or page text
- Latest release: parse `<script>` data
- og:image: `<meta property="og:image">`

**Gotcha:** The full Chrome User-Agent string triggers Cloudflare bot
detection and returns a challenge page. Use the truncated Safari-like UA:
`"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"`.

### 12.2 YouTube (`@handle/videos` pages)

**URL pattern:** `https://www.youtube.com/@{handle}/videos` (or
`/channel/{UC...}/videos` for legacy channel IDs).

**Method:** HTTP fetch, then parse `ytInitialData` from inline `<script>`.

**Layout variants (handle BOTH):**

1. **Current (2026):** `lockupViewModel` blocks. Each block contains:
   - Thumbnail URL with `/vi/{11-char-video-id}/`
   - Sequential `"content": "..."` fields: title, then views, then age
   - View formats vary: `"149K views"` or just `"149K"`
   - Age formats vary: `"6 days ago"` or `"6d ago"`

2. **Legacy fallback:** `videoRenderer` blocks with `"title"`, `"viewCountText"`,
   `"shortViewCountText"`.

**Critical:** which format YouTube returns depends on User-Agent. With the
truncated Safari-like UA we use, both formats can appear across calls. The
parser must handle BOTH.

**Subscribers extraction (resilient — try all three patterns):**

```python
# Pattern 1: accessibility label
re.search(r'"label"\s*:\s*"([\d.,]+\s*[KMBkmb]?\s+[Ss]ubscriber[s]?)"', text)
# Pattern 2: subscriberCountText simpleText
re.search(r'"subscriberCountText"\s*:\s*\{"simpleText"\s*:\s*"([^"]+)"', text)
# Pattern 3: bare "52M subscribers"
re.search(r'([\d.,]+[KMBkmb]?)\s+subscribers', text, re.I)
```

### 12.3 kworb.net

**URL pattern:** `https://kworb.net/spotify/artist/{spotify-artist-id}.html`

**Method:** HTTP fetch (no auth, static HTML). Parse `<table>` rows.

**Per-track row shape:**
```html
<tr>
  <td>{peak_date YYYY/MM/DD}</td>
  <td>{title, optionally prefixed with "* "}</td>
  <td>{total_streams as "1,051,003,425"}</td>
  ... 70+ country chart-position columns
</tr>
```

**Per-artist YouTube pages do NOT exist on kworb (404).** kworb's YouTube
coverage is global only (`/youtube/insane.html`, `/youtube/charts/`). YouTube
per-artist data comes from `harvest_social.harvest_youtube` (§12.2).

### 12.4 Apple Music — iTunes Search API

The Apple Music web pages are JS-rendered and resist scraping (every direct
fetch returns the JS shell). **The iTunes Search API** is a free public JSON
endpoint that returns structured data without authentication:

**Endpoints:**

```
GET https://itunes.apple.com/search?term={name}&entity=musicArtist&limit=5&country={iso}
GET https://itunes.apple.com/lookup?id={artistId}&entity=album&limit=30&sort=recent&country={iso}
GET https://itunes.apple.com/lookup?id={artistId}&entity=song&limit=8&sort=popular&country={iso}
GET https://itunes.apple.com/lookup?id={artistId}&country={iso}
```

**Artist ID resolution:**

1. If `apple_music_url` is present and contains `/artist/{slug}/{id}`, extract
   the numeric ID directly.
2. Otherwise search by name; prefer exact case-insensitive name match;
   fall back to the top hit.

**Release classification (single / EP / album):**

```python
name = collection_name.lower()
if " - single" in name or name.endswith("- single"): "single"
elif " - ep" in name or name.endswith("- ep"):       "ep"
elif track_count <= 3:                                 "single"
else:                                                  "album"
```

**Recent count for KPI 11:**

```python
cutoff_90d = today - 90 days
recent_releases_90d = count(r for r in releases if r.releaseDate >= cutoff_90d)
```

### 12.5 Google News RSS

**URL pattern:**
`https://news.google.com/rss/search?q="{name}" music&hl=en-US&gl=US&ceid=US:en&tbs=qdr:w`

(`tbs=qdr:w` = past week)

**Method:** HTTP fetch. Count `<item>` tags. Extract first 5 `<title>` tags
(skip the channel title at position 0).

**Status detection:**
- `<channel>` present and `<item>` count > 0 → `"ok"`
- `<channel>` missing → `"blocked"` (Google interstitial)
- Otherwise → `"error"`

### 12.6 MusicBrainz

**Endpoint:** `https://musicbrainz.org/ws/2/artist?query={name}&fmt=json&limit=3`

**Rate limit:** 1 req/sec. Use a 1.1-second sleep between artists.

**Relations to extract:**
- `type: "instagram"` → instagram URL
- `type: "youtube"` → YouTube channel URL
- `type: "soundcloud"` → SoundCloud URL
- `type: "social network"` with `url.resource` containing `twitter.com` → X URL
- `type: "social network"` with `url.resource` containing `tiktok.com` → TikTok URL
- `type: "social network"` with `url.resource` containing `facebook.com` → Facebook URL
- `type: "free streaming"` with `url.resource` containing `spotify.com` → Spotify URL

### 12.7 sonymusiclatin.com (legacy / discovery only)

**Status:** Demoted from "source of truth" to "optional enrichment."

**Direct fetch returns 403** on most paths. Use one of:

1. **Wikipedia roster** — `en.wikipedia.org/wiki/Sony_Music_Latin`. Parse the
   wiki table.
2. **Google search** for `site:sonymusiclatin.com/artist`.
3. **Hardcoded seed list** in `scripts/scrape_roster.py` as last resort.

When fetch succeeds, paginated pages live at `/artist/page/{N}/` — note
`/artist/` (singular), not `/artists/`.

---

## 13. Deployment

### 13.1 GCS static hosting (primary)

**Script:** `scripts/deploy-gcs.sh`

**Required env:**
- `GCP_PROJECT_ID`
- `GCP_BUCKET_NAME`

**Steps the script performs:**

1. `gcloud config set project $GCP_PROJECT_ID`
2. `gsutil -m rsync -rd dist/ gs://$GCP_BUCKET_NAME/`
3. Set CORS / cache headers (5 min for index.html, 1 year for assets)
4. `gsutil iam ch allUsers:objectViewer gs://$GCP_BUCKET_NAME/`
5. Print the public URL

### 13.2 Cloud Run (alternative)

`scripts/deploy.py` builds a container that serves `dist/` via a small static
server. Useful if you later want server-side env-var injection.

### 13.3 Firebase / other hosts

`firebase.json` is present; the project is hostable on Firebase Hosting via
`firebase deploy`. Any static host that serves `dist/` works.

### 13.4 npm scripts

```json
{
  "dev":         "vite",
  "build":       "tsc -b && vite build",
  "build:full":  "npm run pipeline && npm run build",
  "pipeline":    ".venv/bin/python scripts/run_pipeline.py",
  "deploy":      "bash scripts/deploy-gcs.sh",
  "ship":        "bash scripts/deploy-gcs.sh",
  "preview":     "vite preview",
  "lint":        "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
  "test":        "vitest"
}
```

---

## 14. Scheduling

### 14.1 launchd plist (macOS production)

**Location when active:** `~/Library/LaunchAgents/com.chromadata.smetracker.plist`

**Source of truth in repo:** `infra/launchd/com.chromadata.smetracker.plist`

**Triggers:** Daily at 06:00 local time.

**Calls:** `/bin/bash /Users/praveer/sme_artistTracker/scripts/cron_refresh.sh`

**Activation:**

```bash
cp infra/launchd/com.chromadata.smetracker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.chromadata.smetracker.plist
launchctl list | grep chromadata   # verify
```

**Manual trigger (without waiting for schedule):**
```bash
launchctl start com.chromadata.smetracker
```

### 14.2 Wrapper script — `scripts/cron_refresh.sh`

Handles the impedance mismatch between launchd's minimal environment and the
interactive shell:

1. `cd` to project root
2. `source .env` (gets `VITE_ANTHROPIC_API_KEY`, etc.)
3. Bridge `VITE_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` (the Python pipeline
   doesn't use the Vite prefix)
4. Restore `PATH` (launchd starts with `/usr/bin:/bin` only); inject
   nvm + homebrew + venv paths
5. Run `npm run build:full` with output appended to `logs/pipeline-{date}.log`
6. Call `scripts/notify.py` with success or failure mode
7. Prune logs older than 30 days
8. Exit with the pipeline's exit code

### 14.3 Wake-from-sleep consideration

`launchd`'s `StartCalendarInterval` only fires when the Mac is awake. If the
machine is asleep at 06:00, launchd runs the job as soon as it wakes. For
guaranteed daily execution, schedule a wake event via `pmset` (out of scope
for the default config; add if needed).

---

## 15. Notifications

### 15.1 Helper — `scripts/notify.py`

Plain-text email via Python's `smtplib`. Supports STARTTLS (port 587) and
SMTP_SSL (port 465).

**Modes:**

- `--mode success` — extracts the "Pipeline Summary" section from the log
- `--mode failure` — includes the Pipeline Summary plus the last 60 lines of
  log so the cause is visible in the email

**Env vars:**

```
SMTP_HOST        smtp.gmail.com / smtp-mail.outlook.com / smtp.sendgrid.net / ...
SMTP_PORT        587 (STARTTLS) or 465 (SSL)
SMTP_USER        SMTP login
SMTP_PASSWORD    SMTP password / app-specific password / API key
SMTP_FROM        (optional) From: address — defaults to SMTP_USER
NOTIFY_EMAIL_TO  recipient — defaults to praveer@chromadata.com
```

**Graceful degradation:** If any of `SMTP_HOST/PORT/USER/PASSWORD` is missing,
the script writes a record to `logs/notifications.log` and exits 0. Pipeline
NEVER fails due to a notification problem.

### 15.2 Success-email window

`SUCCESS_EMAIL_UNTIL` (env var, format `YYYY-MM-DD`) — the wrapper sends a
daily success summary on each successful run **up to and including** this date.
After this date, only failures email. Failures always email regardless.

Initial value: 15 days from rollout. Adjust in `scripts/cron_refresh.sh` or
override via env.

### 15.3 Email content

**Success body** — Pipeline Summary block (phase timings, KPI population, news
counts, output file paths).

**Failure body** — Pipeline Summary + last 60 log lines containing the
traceback or error.

**Both** prepend a small header with hostname, project path, mode, and date.

---

## 16. Curated artist maintenance

### 16.1 Adding an artist

1. Append a block to `data/curated_artists.yaml` under `artists:` with at
   minimum `name` and `slug`.
2. Run `python scripts/build_roster.py` to validate; abort if it errors.
3. Run `npm run build:full` to harvest and rebuild.
4. Commit YAML + any new data files.

### 16.2 Removing an artist

**Prefer `status: archived` over deletion.** Archived artists stop being
harvested / scored / displayed but their historical snapshots and image are
retained. To restore, change `status` back to `active`.

Hard deletion is only appropriate when the artist was added in error.

### 16.3 Renaming

Change `name`. NEVER change `slug` unless you also rename
`data/snapshots/*` and `data/images/{slug}.jpg` so historical data isn't
orphaned.

### 16.4 Marking as legacy estate

Set `status: legacy_estate` and `deceased_date: YYYY-MM-DD`. Effects:

- KPIs 2, 3, 6, 7 nulled with `alert: "legacy_estate"`. Catalog KPIs continue.
- Live-activity news signals (surge, silence, anomaly, decline) suppressed.
- Catalog signals (milestone, new release, Spotify trend, press, Apple Music
  surge) continue to fire.

### 16.5 Updating social links from a client CSV

The client periodically returns a filled
`data/curated_social_links_template.csv` (templated, sent to them
proactively). To merge their updates:

1. Place the filled file at `data/curated_social_links_filled.csv`
2. Run `python scripts/merge_social_links.py --dry-run` to preview
3. Run without `--dry-run` to apply (uses ruamel.yaml to preserve comments)
4. Run `npm run build:full`

The merger validates each URL against the expected domain for its column —
mismatches (a Twitter URL in the Spotify cell, etc.) are logged and skipped,
not merged. This catches client copy-paste errors that would otherwise
silently break harvest.

---

## 17. Edge cases and gotchas

A non-exhaustive list of decisions and traps learned during development.
**Read this before re-implementing or making non-trivial changes.**

### Data quality

- **Velocity overflow**: When yesterday's reach for an artist was effectively
  zero (we lacked a social URL), and today's is normal, the percent change
  can hit millions of %. `1.1 ** (vel - 2.0)` overflows Python's float. Fix:
  skip `rapid_follower_surge` when velocity > 1000% (it's a data
  discontinuity, not news), and clamp the exponent at min(vel-2, 100) for
  safety.

- **Slug stability**: Changing a slug orphans historical data. Make slugs
  immutable; rename the display `name` instead.

- **CSV merger validates by domain**: A Twitter URL accidentally pasted into a
  Spotify column would silently break Spotify harvest with no error. The
  merger drops these (4/287 in the first client batch).

### Platforms

- **Spotify Cloudflare bot wall**: The full Chrome User-Agent string returns
  a challenge page. Use the truncated `"Mozilla/5.0 (Macintosh; Intel Mac OS X
  10_15_7) AppleWebKit/537.36"`.

- **YouTube layout variants**: YouTube serves either `lockupViewModel` (new)
  or `videoRenderer` (legacy) depending on User-Agent and rotating A/B
  cohorts. The parser must handle both. View-count formats vary: `"149K views"`
  vs. `"149K"` vs. an `accessibilityText` with a comma-separated full number.

- **Apple Music pages are JS-only**: Don't try to scrape `music.apple.com`
  directly. Use the iTunes Search API instead.

- **kworb has no per-artist YouTube pages**: Don't try
  `kworb.net/youtube/artist/...` — 404. kworb covers per-artist Spotify only.

- **MusicBrainz rate limit**: 1 req/sec. Always sleep ≥ 1.1s between calls.

- **Google News RSS occasionally blocks**: If `<channel>` is missing in the
  response, treat as `blocked` and retry next day; don't loop.

### Pipeline

- **No Anthropic key → fall back to templates**: The pipeline must produce a
  briefing even without an LLM. `generate_news.py --no-ai` uses template
  blurbs.

- **Phase 2 is the slowest** (~10 minutes). Run with `--limit 5` for
  development; the pipeline is otherwise designed for nightly batch.

- **Idempotent re-runs**: All phases produce the same output given the same
  inputs (modulo network variability). Safe to re-run after a partial failure.

### Frontend

- **Bundle size**: All JSON data is baked into the production bundle via
  `import.meta.glob`. The bundle grows roughly 100 KB/week as snapshot files
  accumulate. Switch to runtime data fetching above ~5 MB raw — prune
  `data/snapshots/*.json` files older than 14 days as the simpler interim fix.

- **Search auto-expand**: `ArtistCard`'s `initiallyExpanded` prop is synced
  via `useEffect` so search-driven narrowing reacts in real time. The user
  can still manually collapse a search-expanded card.

- **Static after build**: There are no runtime API calls. Don't add them
  without redesigning state management.

### Operations

- **launchd minimal env**: `PATH` is `/usr/bin:/bin` only. `cron_refresh.sh`
  restores nvm/homebrew/venv paths.

- **.env loaded by wrapper, not by plist**: Secrets stay out of the plist
  (which is otherwise version-controlled).

- **`VITE_ANTHROPIC_API_KEY` vs. `ANTHROPIC_API_KEY`**: Vite requires the
  `VITE_` prefix to expose vars to the browser. The Python pipeline reads the
  bare name. The wrapper bridges them.

- **`.env` is gitignored**: The `.env.example` in the repo lists every var
  the system uses, but with placeholder values. Real secrets live in `.env`.

---

## 18. Reimplementation checklist

If a new team is reimplementing this from scratch, this is the build order
that minimizes blocked progress:

### Week 1 — Foundation

1. Create project: `npm create vite@latest` (React + TS template); install
   Tailwind 4 + the design tokens in §11.2.
2. Set up Python venv. Install `requirements.txt`.
3. Stub `data/curated_artists.yaml` with 5–10 test artists (use existing
   slugs to validate).
4. Implement `scripts/build_roster.py` (§9.1).
5. Implement `src/data/types.ts` (§6) + `src/data/loader.ts`.
6. Implement `App.tsx` with a roster grid only (use placeholders for KPIs).
   Goal: see the 10 test artists' images render in a Tailwind grid.

### Week 2 — Pipeline (Phase 2)

1. Implement `harvest_social.py` for Spotify, YouTube, and Google News only
   (the three highest-value sources).
2. Wire the kworb augmenter (`harvest_kworb.py`) and iTunes harvester
   (`harvest_itunes.py`).
3. Sanity-test by running phase 2 against the 10 test artists; produce a
   snapshot JSON.
4. Add Instagram, TikTok, X, Facebook (these depend on aggregator search;
   harder to wire — defer if necessary).

### Week 3 — Pipeline (Phases 3 + 4)

1. Implement `compute_kpis.py` (§7 formulas).
2. Implement `generate_news.py` with **template blurbs only** — defer the
   Anthropic integration to the next phase.
3. Render the news feed in the frontend.

### Week 4 — Polish + AI

1. Add the Anthropic API integration to `generate_news.py`.
2. Implement the KPI leaderboards.
3. Add the AI Analyst tab (chat UI calling Anthropic with built system
   prompt).
4. Wire `run_pipeline.py` orchestrator.

### Week 5 — Productionization

1. Implement `cron_refresh.sh` + the launchd plist.
2. Wire `notify.py` and SMTP.
3. Set up GCS deployment (`deploy-gcs.sh`).
4. Document any deviations from this spec for the team's records.

### Critical path

Phases 1, 2, 3 (in that order) are the critical path. Frontend can be built
in parallel against the schema. The Anthropic integration and the news
scoring rubric are independent and can ship later than core KPIs.

---

## 19. Testing strategy

- **Unit-level**: Each pure helper function (slugify, parse_abbrev,
  _video_momentum, etc.) is small enough to test inline. Use `pytest`.
- **Integration**: `scripts/build_roster.py --no-enrich` should run cleanly on
  the curated YAML and produce a roster.json that validates against the
  schema in §6.2.
- **Pipeline smoke**: `npm run pipeline -- --limit 3 --no-ai` should complete
  in under 2 minutes and produce all expected output files.
- **Frontend**: `npx tsc -p tsconfig.app.json --noEmit` for type-check.
  `vitest` for any component tests added.
- **Visual**: Run `npm run dev` and click through each tab. Especially verify
  the artist roster search auto-expands on a single match, the news ticker
  loops smoothly, and Vicente Fernández's card shows `legacy_estate`
  treatment correctly (KPIs 2/3/6/7 dashed out).

---

## 20. Appendix

### 20.1 Slug convention

Lowercase ASCII + digits + hyphens. Diacritics stripped:

```
"Carlos Vives"        → carlos-vives
"Natalia Lafourcade"  → natalia-lafourcade
"C. Tangana"          → c-tangana
"Ha*Ash"              → ha-ash       (asterisk dropped)
"DARUMAS"             → darumas
"Beéle"               → beele
```

### 20.2 Date conventions

All dates ISO 8601 (`YYYY-MM-DD`). All times UTC unless noted. Timestamps
that include time use ISO 8601 with timezone (`YYYY-MM-DDTHH:MM:SS+00:00`).

### 20.3 File naming

- Snapshots: `YYYY-MM-DD.json` (raw harvest) and `YYYY-MM-DD-kpis.json`
  (computed)
- News: `YYYY-MM-DD.json` (in `data/news/`)
- Images: `{slug}.jpg`
- Logs: `pipeline-YYYY-MM-DD.log`

### 20.4 Common regex patterns

```python
# Spotify artist ID from URL
re.search(r"open\.spotify\.com/artist/([A-Za-z0-9]{22})", url)

# YouTube channel handle from URL
re.search(r"youtube\.com/@([^/?&]+)", url)

# YouTube video ID from thumbnail URL
re.search(r"/vi/([A-Za-z0-9_-]{11})/", html)

# Apple Music artist ID from URL
re.search(r"/artist/[^/]+/(\d+)", url)

# Abbreviated number (149K, 1.2M, 14.7B)
re.match(r"([\d.,]+[KMBkmb]?)", text)
```

### 20.5 Glossary

- **A&R** — Artist & Repertoire. The Sony team that signs and develops artists.
- **Tier** (artist) — Reach-based bucket: mega / major / rising / emerging.
- **Estate** — A deceased artist's catalog, managed posthumously.
- **Snapshot** — A single day's harvested data file.
- **KPI snapshot** — The computed-KPI counterpart to a harvest snapshot.
- **Briefing** — The Top 15 news items for a given day.
- **Curated list** — The hand-maintained `data/curated_artists.yaml`.
- **Roster** — The output of `build_roster.py` — i.e., the curated list
  enriched with metadata and serialized as JSON for downstream consumption.
- **Phase 1c** — Image discovery; runs after Phase 1b (social-link enrichment).
- **SML** — Sony Music Latin (`sonymusiclatin.com`).
- **Lusophone** — Portuguese-speaking, primarily Brazil and Portugal.

### 20.6 Sample env file

See `.env.example` in the repo root. Required at minimum:

```
ANTHROPIC_API_KEY=sk-ant-...
VITE_ANTHROPIC_API_KEY=sk-ant-...   # same value; frontend AI Analyst tab
```

Optional but recommended for production:

```
GCP_PROJECT_ID=...
GCP_BUCKET_NAME=...
SMTP_HOST=...
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
NOTIFY_EMAIL_TO=praveer@chromadata.com
SUCCESS_EMAIL_UNTIL=2026-06-10
```

### 20.7 Reference links

- Anthropic Claude API docs: https://docs.anthropic.com
- iTunes Search API: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/
- MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
- kworb.net (Spotify per-artist): pattern documented in §12.3
- Vite documentation: https://vitejs.dev
- Tailwind CSS: https://tailwindcss.com
- launchd reference: `man launchd.plist`

---

## 21. Change log

| Date | Change | Author |
|------|--------|--------|
| 2026-04-29 | Initial curated-roster architecture; replace SML scrape with YAML | Chromadata |
| 2026-04-29 | Add 46 customer-curated artists; introduce `legacy_estate` handling | Chromadata |
| 2026-04-30 | Pipeline verified end-to-end with curated roster | Chromadata |
| 2026-05-05 | Frontend: search input on roster page; Overview moved to last tab | Chromadata |
| 2026-05-05 | Spotify-first image discovery; YouTube `lockupViewModel` parser; kworb Spotify; iTunes Search API; KPI 8 renamed; KPI 11 added | Chromadata |
| 2026-05-27 | Client-provided social URLs merged (283 of 287 valid); CSV-merge validator catches 4 client copy-paste errors | Chromadata |
| 2026-05-27 | launchd 06:00 daily schedule; success/failure email notifications | Chromadata |
| 2026-05-27 | This document written | Chromadata |

---

**End of specification.** Anything not covered here is intentionally
unspecified and left to the implementer's judgment. When in doubt, prefer
the simpler approach and match the existing codebase's conventions (see §4).
