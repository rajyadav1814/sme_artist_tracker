// ─── Roster ────────────────────────────────────────────────────────────────

export interface SocialLinks {
  instagram:   string | null;
  youtube:     string | null;
  tiktok:      string | null;
  x:           string | null;
  spotify:     string | null;
  apple_music: string | null;
  facebook:    string | null;
}

// ─── Curated metadata ──────────────────────────────────────────────────────
// Optional fields populated by data/curated_artists.yaml via build_roster.py.
// Existing code that reads only the legacy fields keeps working unchanged.

export type LabelStatus =
  | 'sony-latin'
  | 'sony-brasil'
  | 'sony-spain'
  | 'sony-mexico'
  | 'non-sony'
  | 'unconfirmed';

export type EntityType  = 'solo' | 'duo' | 'group' | 'estate';
export type ArtistStatus = 'active' | 'hiatus' | 'legacy_estate' | 'archived';
export type ArtistPriority = 'high' | 'standard' | 'rising' | 'catalog';

export interface ArtistMember {
  name: string;
  slug: string;
}

export interface RosterArtist {
  name:             string;
  slug:             string;
  profile_url:      string;
  image_url:        string;
  image_local_path: string;
  bio_excerpt:      string;
  social_links:     SocialLinks;

  // Curated metadata (optional — undefined for legacy/scraped entries)
  country?:         string;
  primary_market?:  string;
  genre_tags?:      string[];
  label_division?:  string;
  label_status?:    LabelStatus;
  entity_type?:     EntityType;
  members?:         ArtistMember[];
  status?:          ArtistStatus;
  deceased_date?:   string;
  priority?:        ArtistPriority;
  aliases?:         string[];
  notes?:           string;
}

export interface Roster {
  roster_date:   string;
  source:        string;
  artist_count:  number;
  artists:       RosterArtist[];
}

// ─── Snapshot ───────────────────────────────────────────────────────────────

export interface KpiEntry {
  kpi_id:          number;
  kpi_name:        string;
  unit?:           string;
  current_value:   number | null;
  previous_value:  number | null;
  delta_absolute:  number | null;
  delta_percent:   number | null;
  trend:           'up' | 'down' | 'flat' | 'unknown';
  benchmark_tier:  string | null;
  alert:           string | null;
  // extra fields from pipeline
  [key: string]:   unknown;
}

export type ArtistTier = 'mega' | 'major' | 'rising' | 'emerging';

export interface SnapshotArtist {
  artist_slug:  string;
  artist_name:  string;
  tier:         ArtistTier;
  kpis:         KpiEntry[];
  // Curated metadata passed through from roster.json (may be undefined)
  country?:      string;
  label_status?: LabelStatus;
  status?:       ArtistStatus;
  priority?:     ArtistPriority;
  genre_tags?:   string[];
}

export interface Snapshot {
  snapshot_date:          string;
  previous_snapshot_date: string;
  artists:                SnapshotArtist[];
}

// ─── News ────────────────────────────────────────────────────────────────────

export interface NewsKpiImpact {
  kpi_id:          number;
  kpi_name:        string;
  delta_absolute?: number | null;
  delta_percent?:  number | null;
  current_value?:  number | null;
  direction?:      'up' | 'down' | 'flat' | string;
  benchmark_tier?: string | null;
}

export interface NewsItem {
  priority:        number;
  score:           number;
  signal_type:     string;
  headline:        string;
  artist_name:     string;
  artist_slug:     string;
  artist_tier:     ArtistTier;
  image_url?:      string | null;
  kpi_impact:      NewsKpiImpact[];
  summary:         string;
  source:          string;
  data_confidence: string;
  timestamp:       string;
  // extra fields from pipeline
  [key: string]:   unknown;
}

export interface NewsBriefing {
  news_date:        string;
  source_snapshot:  string;
  items:            NewsItem[];
}
