---
name: sony-latin-pulse
description: >
  Build and refresh a Sony Music Latin artist intelligence dashboard — a "journalist bureau"
  that scrapes https://www.sonymusiclatin.com/artists/, harvests every artist's social-media
  links, pulls live metrics and recent activity from each platform, computes 10 core KPIs,
  and surfaces the Top 15 newsworthy changes daily. Output is a black-and-white web app with
  round artist headshots matching the label's own design language. Use this skill whenever the
  user mentions Sony Music Latin artists, Latin music artist tracking, social media monitoring
  for a music label roster, daily artist intelligence reports, or wants a journalist-style
  news feed of Latin artist activity. Also trigger when the user asks to scrape
  sonymusiclatin.com, build a music-artist KPI dashboard, or monitor artist social metrics
  over time.
---

# Sony Latin Pulse — Artist Intelligence Skill

> **Concept:** You are a digital journalist permanently assigned to the Sony Music Latin beat.
> Your newsroom publishes a daily briefing that surfaces the 15 most important developments
> across every artist on the roster, backed by hard KPI data.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────┐
│  PHASE 1 — ROSTER BUILD                      │
│  Source: data/curated_artists.yaml (authoritative)
│  Optional enrichment: SML detail pages,      │
│   MusicBrainz, Wikipedia (social/image/bio)  │
│  Output: data/roster.json                    │
└──────────────┬───────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│  PHASE 2 — SOCIAL MEDIA HARVEST              │
│  Per artist, per platform:                   │
│  Instagram, YouTube, TikTok, X/Twitter,      │
│  Spotify, Apple Music, Facebook              │
│  Capture: follower counts, recent posts,     │
│  engagement metrics, latest releases         │
└──────────────┬───────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│  PHASE 3 — KPI ENGINE                        │
│  Compute 11 KPIs per artist (see §4)         │
│  Compare to previous snapshot → deltas       │
└──────────────┬───────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│  PHASE 4 — NEWS DESK                         │
│  Rank all changes by significance             │
│  Select Top 15 newsworthy items              │
│  Write editorial-quality blurbs              │
└──────────────┬───────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│  PHASE 5 — DASHBOARD RENDER                  │
│  Black & white web app, round artist images  │
│  Daily refresh, persistent storage           │
└──────────────────────────────────────────────┘
```

---

## 2. Phase 1 — Roster Build

### 2.1 Source of truth

The roster is **curated**, not scraped. `data/curated_artists.yaml` is the
authoritative list of artists the pipeline tracks; it is hand-edited by a
maintainer (currently driven by direct customer input). `scripts/build_roster.py`
reads the YAML and produces `data/roster.json` — the file all downstream phases
and the frontend consume.

The legacy SML scrape (`scripts/scrape_roster.py`) is kept as a *discovery* tool
only — useful for spotting new SML signings the curated list might be missing.
It is no longer wired into the daily pipeline.

### 2.2 Per-Artist Data to Extract

For each artist card on the page, capture:

| Field             | Source                                          |
|-------------------|-------------------------------------------------|
| `name`            | Artist display name from the card heading       |
| `slug`            | URL slug (e.g. `camilo`, `becky-g`)             |
| `profile_url`     | Full link to the artist's SML detail page       |
| `image_url`       | `<img>` src — the square/round headshot         |
| `bio_excerpt`     | First ~300 chars of bio text if visible         |
| `social_links`    | Object keyed by platform → URL                  |

### 2.3 Social Link Discovery

Social links may appear on the artist card OR on the artist's individual detail page.
Always follow `profile_url` and scrape the detail page to ensure complete social links.

Recognized platforms and their URL patterns:

- **Instagram**: `instagram.com/{handle}`
- **YouTube**: `youtube.com/c/{channel}` or `youtube.com/@{handle}`
- **TikTok**: `tiktok.com/@{handle}`
- **X / Twitter**: `twitter.com/{handle}` or `x.com/{handle}`
- **Spotify**: `open.spotify.com/artist/{id}`
- **Apple Music**: `music.apple.com/{locale}/artist/{slug}/{id}`
- **Facebook**: `facebook.com/{handle}`
- **SoundCloud**: `soundcloud.com/{handle}`

### 2.4 Image Handling

Download each artist's headshot image and store locally. The image will be rendered
as a **circle (border-radius: 50%)** in the dashboard, matching the sonymusiclatin.com
visual style. Store images at a consistent size (400×400 or original aspect, CSS handles
the crop).

**Storage path:** `data/images/{artist_slug}.jpg`

---

## 3. Phase 2 — Social Media Harvest

For each artist, visit their social media profiles using web search and web fetch tools.
The goal is to capture **publicly available** data that a journalist would note.

### 3.1 Per-Platform Metrics

| Platform       | Metrics to Capture                                                                                  |
|----------------|------------------------------------------------------------------------------------------------------|
| **Instagram**  | Followers, posts count, recent 5 post captions + like/comment counts, story highlights count         |
| **YouTube**    | Subscribers, total views, recent 3 video titles + view counts + publish dates                        |
| **TikTok**     | Followers, likes total, recent 3 videos + view counts                                                |
| **X / Twitter**| Followers, following count, recent 5 tweets text + engagement (likes/retweets)                       |
| **Spotify**    | Monthly listeners, top 5 tracks + play counts, latest release name + date                            |
| **Apple Music**| Top songs listed, latest release name + date                                                         |
| **Facebook**   | Page likes, followers, recent post engagement                                                        |

### 3.2 Practical Harvesting Strategy

Since not all platforms expose data via unauthenticated scraping, use this priority:

1. **Web search** — Search `"{artist name}" site:instagram.com followers` or similar to
   find publicly reported metrics from social-tracking sites (Social Blade, etc.).
2. **Web fetch** — Attempt direct page fetch for platforms that render public data in HTML
   (YouTube, Spotify profile pages).
3. **Third-party aggregators** — Search sites like Social Blade, Chartmetric, Kworb, or
   HypeAuditor summaries that index public data.
4. **News articles** — Recent press mentioning follower milestones, chart positions, etc.

When exact numbers aren't available, note the most recent reliable estimate and its source
date. Always timestamp every data point.

### 3.3 Data Snapshot Format

Store each harvest as a timestamped JSON snapshot:

```json
{
  "snapshot_date": "2026-04-05",
  "artist_slug": "camilo",
  "artist_name": "Camilo",
  "platforms": {
    "instagram": {
      "followers": 28400000,
      "posts_count": 1245,
      "recent_posts": [
        {
          "date": "2026-04-03",
          "caption_excerpt": "New single out now...",
          "likes": 450000,
          "comments": 12000
        }
      ],
      "data_source": "direct_fetch",
      "data_freshness": "2026-04-05"
    },
    "spotify": {
      "monthly_listeners": 52000000,
      "top_tracks": [...],
      "latest_release": { "title": "...", "date": "..." },
      "data_source": "web_search",
      "data_freshness": "2026-04-04"
    }
  }
}
```

---

## 4. Phase 3 — The 10 Core KPIs

These are the 11 KPIs that matter most to Sony Music Entertainment's regional Latin and Lusophone roster from a business perspective.
Compute each per-artist and track deltas day-over-day.

### KPI Definitions

| #  | KPI Name                          | Formula / Source                                                        | Why It Matters                                                        |
|----|-----------------------------------|-------------------------------------------------------------------------|-----------------------------------------------------------------------|
| 1  | **Total Social Reach**            | Sum of followers across all platforms                                   | Raw audience size; label negotiation leverage                         |
| 2  | **Social Reach Velocity**         | % change in Total Social Reach vs. prior snapshot                       | Growth momentum; early signal of breakout or decline                  |
| 3  | **Engagement Rate**               | (Total likes+comments across recent posts) / Total followers × 100      | Quality of audience connection; signals authentic fanbase              |
| 4  | **Spotify Monthly Listeners**     | Direct from Spotify                                                     | Industry-standard streaming power metric                              |
| 5  | **Spotify Listener Trend**        | % change in monthly listeners vs. prior snapshot                        | Streaming momentum; release impact detection                          |
| 6  | **Content Velocity**              | Number of posts/videos published in last 7 days across all platforms    | Artist activity level; marketing effort indicator                     |
| 7  | **Platform Diversity Score**      | Count of active platforms (posted in last 30 days) / Total platforms    | Distribution risk; single-platform dependency warning                 |
| 8  | **YouTube Weekly Velocity**       | Average views across 5 most recent YouTube videos                       | Visual content performance; music video launch success                |
| 9  | **Latest Release Recency (days)** | Days since last release on Spotify or Apple Music (whichever is fresher) | Release pipeline health; flags artists going dark                     |
| 10 | **News & Press Mentions**         | Count of unique news articles mentioning artist in past 7 days          | PR momentum; measures cultural relevance beyond owned channels        |
| 11 | **Apple Music Catalog Activity**  | Count of singles/EPs/albums on iTunes in last 90 days                   | Apple Music release cadence; reach into premium listening demographic |

### Delta Tracking

For each KPI, store:
- `current_value` — today's computed value
- `previous_value` — last snapshot's value
- `delta_absolute` — raw change
- `delta_percent` — percentage change
- `trend` — `"up"`, `"down"`, or `"flat"` (±1% threshold for flat)

---

## 5. Phase 4 — The News Desk (Top 15 Newsworthy Items)

You are a journalist. Think like an editor deciding what goes above the fold.

### 5.1 Newsworthiness Scoring

Rank every detected change across all artists using this scoring rubric:

| Signal                                         | Weight | Examples                                                   |
|------------------------------------------------|--------|------------------------------------------------------------|
| **Milestone crossing**                         | 10     | Crossed 10M, 25M, 50M, 100M followers on any platform     |
| **New release detected**                       | 9      | New single, album, or music video dropped                  |
| **Viral spike**                                | 8      | Single post/video >5× average engagement                   |
| **Collaboration or feature detected**          | 8      | Post/track featuring another major artist                  |
| **Rapid follower surge**                       | 7      | >2% daily follower growth on any platform                  |
| **Engagement anomaly**                         | 7      | Engagement rate shifted >50% from baseline                 |
| **Chart entry or movement**                    | 9      | Billboard, Spotify Top 50, Apple Music chart movement      |
| **Tour / event announcement**                  | 6      | Dates, venue announcements, festival bookings              |
| **Award or nomination**                        | 8      | Grammy, Latin Grammy, Billboard Latin Music Award          |
| **Controversy or PR event**                    | 7      | Significant press coverage of non-music event              |
| **Platform silence**                           | 5      | No posts in 14+ days on a previously active platform       |
| **Declining metrics**                          | 5      | Sustained drop in listeners/followers over multiple days    |

### 5.2 Editorial Output Format

For each of the Top 15 items, produce:

```
HEADLINE: [Punchy, journalist-style headline]
ARTIST: [Name]
KPI IMPACT: [Which KPI(s) this affects + delta]
SUMMARY: [2-3 sentence editorial blurb — factual, no hype, cite data]
SOURCE: [Where the data came from]
PRIORITY: [1-15 ranking]
TIMESTAMP: [When detected]
```

### 5.3 Journalist Voice Guidelines

- Write like a Billboard or Rolling Stone reporter, not a press release
- Lead with the most interesting fact
- Include specific numbers: "gained 340K followers" not "gained a lot of followers"
- Compare to context: "fastest growth on the roster this week"
- Flag anomalies: "first time below 20M monthly listeners since August"

---

## 6. Phase 5 — Dashboard Render

### 6.1 Design System — Black & White

The dashboard uses a **strictly monochrome** palette:

```css
:root {
  --bg-primary: #0A0A0A;
  --bg-secondary: #141414;
  --bg-card: #1A1A1A;
  --bg-card-hover: #222222;
  --text-primary: #FFFFFF;
  --text-secondary: #999999;
  --text-muted: #666666;
  --border: #2A2A2A;
  --border-light: #333333;
  --accent-up: #FFFFFF;       /* White for positive trends */
  --accent-down: #666666;     /* Gray for negative trends */
  --accent-highlight: #E0E0E0;/* Near-white for emphasis */
}
```

No color — not even for charts. Use varying shades of gray, white text weight/size,
and spatial hierarchy to communicate importance.

### 6.2 Typography

Use a bold editorial font stack:

- **Headlines**: `"Playfair Display", Georgia, serif` — weight 900
- **Body / Data**: `"IBM Plex Mono", "SF Mono", monospace` — for KPI numbers
- **UI Labels**: `"Inter", "Helvetica Neue", sans-serif` — weight 500
- Import from Google Fonts in the HTML `<head>`.

### 6.3 Layout Structure

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER: "SONY LATIN PULSE" + date + "DAILY BRIEFING"      │
├─────────────────────────────────────────────────────────────┤
│  TOP 15 NEWS TICKER (horizontal scroll or vertical feed)    │
│  Each item: headline, artist round image, KPI badge, blurb  │
├─────────────────────────────────────────────────────────────┤
│  ARTIST ROSTER GRID                                          │
│  Round images (border-radius: 50%) in a responsive grid     │
│  Each card shows: image, name, top 3 KPIs, trend arrows     │
│  Click/tap to expand full KPI detail panel                   │
├─────────────────────────────────────────────────────────────┤
│  KPI LEADERBOARDS                                            │
│  Horizontal tables: top 5 artists per KPI                   │
│  Sortable columns                                            │
├─────────────────────────────────────────────────────────────┤
│  FOOTER: Last refresh timestamp, data sources, version       │
└─────────────────────────────────────────────────────────────┘
```

### 6.4 Artist Card Design

Each artist card in the grid:

```
┌────────────────────┐
│    ╭──────────╮    │
│    │  ROUND   │    │  ← 120px circle, grayscale filter,
│    │  IMAGE   │    │    white border 2px
│    ╰──────────╯    │
│   Artist Name      │  ← Playfair Display, 16px, bold
│   28.4M reach      │  ← IBM Plex Mono, 13px, muted
│   ▲ 2.3%  ▼ 0.1%  │  ← trend arrows, white=up gray=down
│   52M listeners    │
└────────────────────┘
```

CSS for round images:
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
  filter: grayscale(0%);  /* Reveal color on hover */
}
```

### 6.5 News Item Card Design

```
┌──────────────────────────────────────────────────────────┐
│ #1  ╭───╮  BECKY G CROSSES 40M INSTAGRAM FOLLOWERS      │
│     │ ○ │  KPI: Total Social Reach ▲ +1.2M (3.1%)       │
│     ╰───╯  The "Sin Pijama" singer surpassed the 40M    │
│            milestone on Instagram, making her the...      │
│            4 hours ago · Instagram                        │
└──────────────────────────────────────────────────────────┘
```

### 6.6 Implementation Notes

- Build as a **single-file HTML** (with inline CSS/JS) or a **React .jsx artifact**
- Use `persistent_storage` API to store snapshots across sessions:
  - `await window.storage.set('roster', JSON.stringify(roster))`
  - `await window.storage.set('snapshot:2026-04-05', JSON.stringify(data))`
  - `await window.storage.set('news:2026-04-05', JSON.stringify(top15))`
- On load, compare current snapshot to last stored → compute deltas
- If deploying to GCP Cloud Storage, output as a static HTML file

---

## 7. Data Persistence & Daily Refresh Strategy

### 7.1 Storage Schema

Use hierarchical keys with the persistent storage API:

| Key Pattern                            | Content                                 |
|----------------------------------------|-----------------------------------------|
| `roster`                               | Full artist roster with metadata        |
| `snapshot:{YYYY-MM-DD}`               | Complete KPI snapshot for that date     |
| `news:{YYYY-MM-DD}`                   | Top 15 news items for that date         |
| `history:{artist_slug}`               | Rolling 30-day KPI history for artist   |
| `images:{artist_slug}`                | Base64 or URL reference for headshot    |

### 7.2 Refresh Logic

On each daily run:

1. **Load previous snapshot** from storage
2. **Scrape roster** — detect new artists or removed artists (itself a newsworthy event)
3. **Harvest social data** for all artists
4. **Compute KPIs** with deltas against previous snapshot
5. **Run news desk** to rank and select top 15
6. **Store new snapshot** and news
7. **Render dashboard** with fresh data

### 7.3 Change Detection for Returning Users

When the dashboard loads:
- Show a **"NEW SINCE YOUR LAST VISIT"** badge on news items the user hasn't seen
- Highlight artists with significant changes since last viewed snapshot
- Animate KPI numbers counting up/down to their new values

---

## 8. Execution Workflow

When this skill is triggered, follow these steps in order:

### Step 1: Build the Roster
Read `data/curated_artists.yaml` — the customer-curated authoritative list of
artists the pipeline tracks. This file is hand-maintained; do not modify it
programmatically except via `scripts/build_roster.py`. For any artist with
missing social_links / image_url / bio_excerpt, optionally enrich from the
SML detail page (works for Sony Latin/Mexico artists), MusicBrainz (broader
coverage), or Wikipedia.

### Step 2: Enrich with Social Links
For each artist, search for their official social media profiles. Prioritize:
- Their individual SML profile page
- Verified accounts on each platform
- Cross-reference with search results

### Step 3: Harvest Metrics (Batched)
Process artists in batches of 5-10. For each batch:
- Run parallel web searches for social metrics
- Fetch Spotify/YouTube profiles where accessible
- Log data freshness for each metric

### Step 4: Compute KPIs
Apply the 11 KPI formulas from §4. If this is the first run, there are no deltas —
store as baseline. On subsequent runs, compute all deltas.

### Step 5: Generate News Briefing
Score all changes using the §5.1 rubric. Select top 15. Write editorial blurbs
following the journalist voice guidelines.

### Step 6: Build the Dashboard
Generate the web app per §6 specifications. Use the frontend-design skill's guidance
for polish and aesthetics. Output as a single HTML file or React artifact.

### Step 7: Persist Data
Store all data using the persistent storage API so the next session can compute
meaningful deltas.

---

## 9. Edge Cases & Resilience

- **403 / blocked pages**: Fall back to web search for publicly reported data
- **Missing social links**: Note as `"not_found"` — don't fabricate links
- **Stale data**: Always show the `data_freshness` timestamp; flag data >7 days old
- **New artist added to roster**: Flag as top news item ("NEW SIGNING")
- **Artist removed from roster**: Flag as top news item ("ROSTER CHANGE")
- **Rate limiting**: Space out web fetches; use search aggregators as backup
- **Incomplete metrics**: Show what's available with confidence indicator (●●●○○)

---

## 10. File Output

The final deliverable is one of:

1. **React artifact** (`.jsx`) — for rendering in Claude's artifact viewer with
   persistent storage support
2. **Static HTML** (`.html`) — for deployment to GCP Cloud Storage or any static host
3. **Both** — if the user needs a deployable version and an in-chat preview

Always copy final output to `/mnt/user-data/outputs/` and present via `present_files`.

---

## Quick Reference: Artist Roster

The authoritative roster lives in `data/curated_artists.yaml`. The pipeline tracks **only** artists listed there. Scope spans Sony Music Latin, Sony Music Brasil, Sony Music Spain, Sony Music Mexico, plus select non-Sony Latin/Lusophone artists of strategic interest.

To add or remove artists, edit `data/curated_artists.yaml` directly — see `skill/references/curated-artists.md` for the schema and lifecycle rules.
