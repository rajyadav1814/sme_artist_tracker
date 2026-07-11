# sme_artistTracker — Local Setup Guide

## Quick Start with Claude Code

### 1. Unpack

```bash
tar -xzf sme_artistTracker.tar.gz
cd sme_artistTracker
```

### 2. Project structure

```
sme_artistTracker/
├── CLAUDE.md                                # Claude Code reads this automatically
├── README.md                                # This file
├── skill/                                   # Knowledge base (read-only reference docs)
│   ├── SKILL.md                             # Full skill definition — 5 pipeline phases
│   └── references/
│       ├── kpi-formulas.md                  # KPI calculations & thresholds
│       ├── news-scoring.md                  # Newsworthiness ranking rubric
│       └── scraping-strategy.md             # Platform-specific harvesting notes
├── scripts/                                 # Python pipeline (add as you build)
├── src/                                     # React frontend (add as you build)
│   ├── components/
│   └── data/
├── data/                                    # Pipeline output
│   ├── snapshots/                           # Daily JSON snapshots
│   └── images/                              # Artist headshot images
└── public/                                  # Static assets
```

### 3. Using with Claude Code

In your Antigravity IDE with the Claude Code extension, you can reference the skill directly:

```
@sony-latin-pulse/SKILL.md Build the Phase 5 dashboard as a React app
```

Or give Claude Code the full context in `sme_artistTracker/`:

```
Read SKILL.md and all files in references/. Then execute the full pipeline:
1. Scrape the Sony Music Latin roster
2. Harvest social media metrics for each artist
3. Compute KPIs
4. Generate the Top 15 news briefing
5. Build the black-and-white dashboard as a deployable web app
```

### 4. Recommended local stack

| Layer            | Suggested Tech                                                    |
| ---------------- | ----------------------------------------------------------------- |
| Frontend         | React + Vite (or Next.js)                                         |
| Styling          | Tailwind CSS (monochrome config)                                  |
| Data persistence | JSON files → SQLite → Cloud Firestore                             |
| Scheduling       | cron job or Cloud Scheduler                                       |
| Deployment       | GCP Cloud Storage (static) or Cloud Run                           |
| Scraping runtime | Node.js (Puppeteer/Playwright) or Python (requests/BeautifulSoup) |

### 5. Development phases

**Phase A — Static prototype**
Get the dashboard rendering with hardcoded sample data. Nail the black-and-white
design, round images, typography, and layout.

**Phase B — Live scraping**
Build the roster scraper and social media harvester. Store snapshots as JSON.

**Phase C — KPI engine**
Implement the 10 KPI calculations with delta tracking.

**Phase D — News desk**
Build the scoring algorithm and editorial blurb generator (can use Claude API).

**Phase E — Daily automation**
Set up cron/scheduler for daily refresh. Deploy to GCP.

### 6. Environment variables (when you get to deployment)

```env
# Optional — for enhanced data gathering
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
YOUTUBE_API_KEY=
ANTHROPIC_API_KEY=         # For AI-generated editorial blurbs
GCP_PROJECT_ID=
GCP_BUCKET_NAME=
```

### 7. Key Claude Code prompts to get started

```
# Scaffold the project
"Initialize a Vite + React + Tailwind project for the Sony Latin Pulse dashboard.
Use the monochrome design system from SKILL.md §6."

# Build the scraper
"Create a Python script that scrapes sonymusiclatin.com/artists/ for the full
artist roster with social media links. Follow references/scraping-strategy.md."

# Generate sample data
"Create realistic sample data for 15 Sony Music Latin artists with all 10 KPIs
populated, including deltas. Output as data/sample-snapshot.json."

# Build the news desk
"Implement the news scoring algorithm from references/news-scoring.md.
Take two snapshots as input and output the top 15 ranked news items."
```
