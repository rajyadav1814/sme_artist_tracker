# KPI Calculation Reference

## Detailed Formulas & Thresholds

### KPI 1: Total Social Reach
```
total_reach = instagram.followers
            + youtube.subscribers
            + tiktok.followers
            + twitter.followers
            + facebook.page_likes
            + spotify.monthly_listeners
```
**Tier Benchmarks:**
- Mega: >50M total reach
- Major: 10M–50M
- Rising: 1M–10M
- Emerging: <1M

### KPI 2: Social Reach Velocity
```
velocity = ((current_reach - previous_reach) / previous_reach) * 100
```
**Alert Thresholds:**
- 🔥 Breakout: >5% daily
- ▲ Strong: 2–5% daily
- → Steady: ±1% daily
- ▼ Declining: < -1% daily
- 🚨 Freefall: < -5% daily

### KPI 3: Engagement Rate
```
total_engagement = sum(likes + comments) across last 10 posts (all platforms)
engagement_rate = (total_engagement / total_reach) * 100
```
**Benchmarks (music industry):**
- Excellent: >3.5%
- Good: 1.5–3.5%
- Average: 0.5–1.5%
- Low: <0.5%

### KPI 4: Spotify Monthly Listeners
Direct value from Spotify profile. No formula needed.

**Tier Benchmarks:**
- Global Star: >50M
- Regional Power: 20M–50M
- Strong: 5M–20M
- Growing: 1M–5M
- Niche: <1M

### KPI 5: Spotify Listener Trend
```
trend = ((current_listeners - previous_listeners) / previous_listeners) * 100
```
Context: New release typically spikes 20-100% then normalizes over 4-6 weeks.

### KPI 6: Content Velocity
```
content_velocity = count(posts published in last 7 days across all platforms)
```
**Benchmarks:**
- Hyperactive: >14 posts/week
- Active: 7–14
- Moderate: 3–7
- Low: 1–3
- Silent: 0

### KPI 7: Platform Diversity Score
```
active_platforms = count(platforms with post in last 30 days)
total_platforms = count(platforms where artist has account)
diversity_score = active_platforms / total_platforms
```
**Risk Assessment:**
- 1.0: Fully diversified
- 0.7–0.99: Healthy
- 0.5–0.69: Some gaps
- <0.5: Platform dependency risk

### KPI 8: YouTube Weekly Velocity
```
recent_videos = 5 most recent YouTube videos (parsed from channel /videos lockupViewModel)
velocity = average(views across recent_videos)
```
Renamed from "Video View Momentum" — formula now isolates YouTube as the
primary driver of music video performance and visual-content algorithmic push.
Falls back to TikTok recent-video views only if the artist has no YouTube channel.

Compare to artist's own 30-day average for context.

### KPI 9: Latest Release Recency
```
spotify_date    = sp.latest_release.date
apple_date      = am.latest_release.date     (from iTunes Search API)
release_date    = max(spotify_date, apple_date)   # most recent wins
recency_days    = today - release_date
```
Cross-checked across Spotify and Apple Music — uses whichever platform indexed
the latest drop first (Apple's iTunes Search often surfaces remixes / singles
a few days before Spotify's metadata catches up).

**Flags:**
- Fresh: 0–14 days (in release window)
- Recent: 15–60 days
- Aging: 61–120 days
- Overdue: 121–180 days
- Dark: >180 days (flag to A&R)

### KPI 10: News & Press Mentions
```
mentions = count(unique articles mentioning artist in last 7 days)
```
Source: web search results count for `"{artist name}" music news` filtered to past week.

**Benchmarks:**
- Trending: >20 mentions/week
- Visible: 10–20
- Moderate: 5–10
- Quiet: 1–5
- Off-radar: 0

### KPI 11: Apple Music Catalog Activity
```
recent_releases_90d = count(album/EP/single on iTunes Search API
                            with releaseDate within last 90 days)
```
Source: `itunes.apple.com/lookup?id={artistId}&entity=album&sort=recent`.
Apple Music's web pages are JS-rendered; iTunes Search API is the project's
authoritative Apple source.

**Tiers:**
- Hyperactive: 5+ releases / 90d
- Active: 3–4
- Moderate: 1–2
- Dormant: 0

The `extra` payload also carries:
- `total_albums` — depth of catalog (proxy for tenure)
- `top_songs` — Apple Music's popularity-ranked tracks (display only)
- `latest_release` — title, date, type (album/EP/single)
- `primary_genre` — Apple's genre classification

---

## Delta Computation

For every KPI, compute:

```json
{
  "kpi_id": 1,
  "kpi_name": "Total Social Reach",
  "current_value": 28400000,
  "previous_value": 27900000,
  "delta_absolute": 500000,
  "delta_percent": 1.79,
  "trend": "up",
  "benchmark_tier": "Major",
  "alert": null
}
```

Trend classification:
- `"up"`: delta_percent > 1%
- `"down"`: delta_percent < -1%
- `"flat"`: delta_percent between -1% and 1%
