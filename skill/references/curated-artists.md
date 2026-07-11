# Curated Artists — Maintenance Reference

The pipeline tracks **only** artists listed in `data/curated_artists.yaml`. This document is the schema reference and lifecycle guide.

## How the curated list flows through the system

```
data/curated_artists.yaml          ← hand-edited, source of truth
        │
        ▼
scripts/build_roster.py            ← reads YAML, optionally enriches
        │                            from SML detail pages, preserves
        │                            prior roster.json metadata
        ▼
data/roster.json                   ← consumed by everything downstream
        │
        ├─→ scripts/enrich_links.py    (Phase 1b: MusicBrainz social links)
        ├─→ scripts/harvest_social.py  (Phase 2: per-platform metrics)
        ├─→ scripts/compute_kpis.py    (Phase 3: 10 KPIs + deltas)
        ├─→ scripts/generate_news.py   (Phase 4: Top 15 briefing)
        └─→ src/data/loader.ts         (Frontend: bundled at build time)
```

## Schema

```yaml
artists:
  - name: "Display Name"            # required — used in UI
    slug: "url-safe-slug"           # required — IMMUTABLE key
    aliases: ["Alt Name"]           # optional — for matching legacy data
    country: "ISO-2"                # optional — e.g. "AR", "BR", "ES"
    primary_market: "free text"     # optional
    genre_tags: [pop, urbano]       # optional — tag list
    label_division: "free text"     # optional — e.g. "Sony Music Brasil"
    label_status: "..."             # optional — see allowed values below
    entity_type: "..."              # optional — solo | duo | group | estate
    members:                        # required when entity_type is duo/group
      - { name: "Member Name", slug: "member-slug" }
    status: "..."                   # optional — active | hiatus | legacy_estate | archived
    deceased_date: "YYYY-MM-DD"     # optional — used with status=legacy_estate
    priority: "..."                 # optional — high | standard | rising | catalog
    social_links:                   # optional — manual override (wins over scraper)
      instagram: "https://..."
      spotify:   "https://..."
    image_url: "https://..."        # optional — manual override
    bio_excerpt: "..."              # optional — manual override
    notes: "free text"              # optional — comments for maintainers
```

### Allowed enum values

| Field          | Allowed values                                                                          |
|----------------|-----------------------------------------------------------------------------------------|
| `label_status` | `sony-latin`, `sony-brasil`, `sony-spain`, `sony-mexico`, `non-sony`, `unconfirmed`     |
| `entity_type`  | `solo`, `duo`, `group`, `estate`                                                        |
| `status`       | `active`, `hiatus`, `legacy_estate`, `archived`                                         |
| `priority`     | `high`, `standard`, `rising`, `catalog`                                                 |

`scripts/build_roster.py` validates these at load time and exits non-zero if any value is out of range.

## Lifecycle

### Adding an artist
1. Append a YAML block under `artists:`. Required fields: `name`, `slug`.
2. Run `python scripts/build_roster.py` to validate and produce `data/roster.json`.
3. Run the full pipeline: `npm run pipeline`.
4. Commit the YAML.

The first daily run will baseline the artist's metrics (no deltas). Subsequent runs produce deltas and news.

### Removing an artist
**Prefer `status: archived` over deletion.** Archived artists:
- Stop being harvested / scored / displayed
- Keep their historical snapshots in `data/snapshots/` and headshot in `data/images/`
- Can be restored by changing `status` back to `active`

Hard deletion (removing the YAML block) is fine for artists that were added in error and never produced useful data.

### Renaming an artist
Change the `name` field, **never the `slug`**. The slug is the file/URL key — changing it orphans historical data. If a slug truly must change (typo, brand change), rename the corresponding files in `data/snapshots/` and `data/images/` in the same commit.

### Marking an artist as a legacy estate
Set `status: legacy_estate` and `deceased_date: YYYY-MM-DD`. Effects:
- KPIs 2 (Reach Velocity), 3 (Engagement Rate), 6 (Content Velocity), 7 (Platform Diversity) → nulled with `alert: "legacy_estate"`. Catalog KPIs (1, 4, 5, 8, 9, 10) continue to compute.
- News signal detectors `follower_surge`, `video_spike`, `platform_silence`, `silence_breaking`, `engagement_anomaly`, `declining_metrics` are suppressed.
- Catalog signals (`milestones`, `spotify_movement`, `fresh_release`, `press_buzz`) still fire — posthumous releases and catalog momentum remain newsworthy.

## Slug convention

Slugs are lowercase ASCII, hyphen-separated, with diacritics stripped:
- "Carlos Vives" → `carlos-vives`
- "Natalia Lafourcade" → `natalia-lafourcade`
- "C. Tangana" → `c-tangana`
- "Ha*Ash" → `ha-ash` (asterisk dropped)
- "DARUMAS" → `darumas`

For groups/duos, the slug uses the group's display name; member slugs follow the same convention. The slug for a member should be unique even if multiple groups have a member with the same first name.

## Manual overrides vs. scraped enrichment

The `social_links`, `image_url`, and `bio_excerpt` fields can be set manually in YAML. When set, manual values **always win** over scraped values. The build process logs whether each artist's data is manual / preserved-from-prior / enriched-from-scrape so you can audit coverage.

The collection workflow for social links:
1. **CSV-first** for client batches: `data/curated_social_links_template.csv` is the format the client fills in. Once returned, a maintainer imports the rows into `social_links:` blocks in the YAML.
2. **MusicBrainz** (Phase 1b) fills gaps the client didn't cover.
3. **SML detail-page scrape** (build_roster.py optional enrichment) fills additional gaps for Sony Latin / Sony Mexico artists.
4. Anything still missing renders as `null` in the dashboard with a "data unavailable" badge.

## Validation

`scripts/build_roster.py` enforces:
- `name` and `slug` are present
- `slug` values are unique across the file
- All enum fields (`label_status`, `entity_type`, `status`, `priority`) use allowed values

Validation runs at the **start** of the build, before any HTTP fetching. Failures exit non-zero with a list of all errors so you fix them in one pass.

## Future scalability

This file is the canonical artifact for now. The intended upgrade path:

| Phase | Trigger | Migration |
|-------|---------|-----------|
| Now — YAML in git | <100 artists, single maintainer | Current state |
| Sheet/Airtable sync | List changes weekly, multiple curators | Add `scripts/sync_curated_list.py` that pulls from a Google Sheet / Airtable into the same YAML. Pipeline downstream untouched. |
| SQLite + admin UI | >500 artists, daily edits, audit trail | Replace `build_roster.py` to read from SQLite. Schema same. |
| Service / API | Multi-tenant | Roster becomes an API call in `build_roster.py`. Same shape. |

The constant: **`data/roster.json` is the contract** between roster management and everything else. Where it comes from changes; what's in it doesn't.
