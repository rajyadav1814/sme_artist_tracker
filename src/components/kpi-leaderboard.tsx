import { useState } from 'react';
import type { SnapshotArtist } from '../data/types';

// ─── Per-KPI accent colours ───────────────────────────────────────────────────
const KPI_COLOR: Record<number, string> = {
  1:  '#60a5fa',  // blue    — Total Social Reach
  2:  '#60a5fa',  // blue    — Reach Velocity
  3:  '#c084fc',  // purple  — Engagement Rate
  4:  '#4ade80',  // green   — Spotify Monthly Listeners
  5:  '#4ade80',  // green   — Spotify Listener Trend
  6:  '#22d3ee',  // cyan    — Content Velocity
  7:  '#2dd4bf',  // teal    — Platform Diversity
  8:  '#f472b6',  // pink    — YouTube Weekly Velocity
  9:  '#fbbf24',  // amber   — Release Recency
  10: '#fb923c',  // orange  — News & Press
  11: '#f87171',  // rose    — Apple Music Catalog Activity
};

// ─── KPI metadata ─────────────────────────────────────────────────────────────

interface KpiMeta {
  name:        string;
  shortName:   string;
  unit:        string;       // suffix appended after value, or '' for none
  format:      'number' | 'percent' | 'recency' | 'posts' | 'ratio' | 'articles';
  invertSort:  boolean;      // true when lower value = better (recency)
}

const KPI_META: Record<number, KpiMeta> = {
  1:  { name: 'Total Social Reach',          shortName: 'Reach',        unit: '',        format: 'number',   invertSort: false },
  2:  { name: 'Social Reach Velocity',       shortName: 'Velocity',     unit: '%',       format: 'percent',  invertSort: false },
  3:  { name: 'Engagement Rate',             shortName: 'Eng. Rate',    unit: '%',       format: 'percent',  invertSort: false },
  4:  { name: 'Spotify Monthly Listeners',   shortName: 'Spotify',      unit: '',        format: 'number',   invertSort: false },
  5:  { name: 'Spotify Listener Trend',      shortName: 'Spotify Δ',    unit: '%',       format: 'percent',  invertSort: false },
  6:  { name: 'Content Velocity',            shortName: 'Posts/wk',     unit: '/wk',     format: 'posts',    invertSort: false },
  7:  { name: 'Platform Diversity Score',    shortName: 'Diversity',    unit: '',        format: 'ratio',    invertSort: false },
  8:  { name: 'YouTube Weekly Velocity',     shortName: 'YT Views',     unit: '',        format: 'number',   invertSort: false },
  9:  { name: 'Latest Release Recency',      shortName: 'Release',      unit: 'd',       format: 'recency',  invertSort: true  },
  10: { name: 'News & Press Mentions',       shortName: 'Press',        unit: '',        format: 'articles', invertSort: false },
  11: { name: 'Apple Music Catalog Activity',shortName: 'AM Releases',  unit: '/90d',    format: 'posts',    invertSort: false },
};

// ─── Business narrative per KPI ───────────────────────────────────────────────
// One concise paragraph per KPI explaining what the metric means in business
// terms and what action it should drive.

const KPI_NARRATIVE: Record<number, string> = {
  1: 'Total Social Reach is the headline number for label negotiations and brand partnerships. It represents the combined addressable audience across every platform — the larger the reach, the greater the leverage when pricing sync deals, sponsorships, and touring guarantees.',
  2: 'Reach Velocity is an early-warning signal. A sustained uptick of 2 %+ daily often precedes a breakout moment — an ideal time to increase marketing spend and pitch editorial playlists before the wave crests. A sustained decline signals audience fatigue or platform disengagement that needs A&R attention.',
  3: 'Engagement Rate separates authentic fanbases from inflated follower counts. A highly engaged smaller audience will convert to ticket sales and merchandise at far higher rates than a passive mega-following. Use this metric to identify artists who are ready for premium brand integrations.',
  4: 'Spotify Monthly Listeners is the industry\'s de facto streaming power metric — used by promoters, labels, and sync agents to gauge real-time commercial relevance. Above 20 M qualifies an artist for headliner status on major festival circuits.',
  5: 'Spotify Listener Trend measures release impact and streaming momentum. A 20 %+ spike typically indicates a successful new drop or playlist addition. Sustained positive trend over multiple weeks signals genuine catalogue growth — a key argument for increased A&R investment.',
  6: 'Content Velocity tracks how actively an artist is feeding the algorithm. Consistent posting (7–14 pieces per week) sustains platform reach without paid promotion. A sudden drop in velocity is often the earliest observable signal of an artist going inactive or entering a contract dispute.',
  7: 'Platform Diversity Score measures distribution risk. An artist reliant on a single platform is vulnerable to algorithm changes or account issues. A score above 0.7 indicates a healthy multi-platform presence that protects revenue streams and reaches different demographic segments.',
  8: 'YouTube Weekly Velocity captures the visual content engine — the primary driver of new fan acquisition. Average views across the artist\'s 5 most recent uploads signal whether music video investments are paying off and whether the artist\'s content is being pushed by YouTube\'s algorithm. Sustained high values predict streaming uplift weeks before it shows on Spotify.',
  9: 'Release Recency tracks how fresh the catalogue is in the streaming ecosystem. Artists beyond 120 days without a release see measurable audience retention decay. Cross-checked across Spotify and Apple Music — uses whichever platform indexed the latest drop first. Use this leaderboard in ascending order to identify artists urgently needing a content drop to re-enter the algorithm cycle.',
  10: 'News & Press Mentions quantify cultural relevance beyond owned channels. High press velocity amplifies all other KPIs — streaming, social growth, and engagement all lift when an artist is in the news cycle. Monitor this metric to time campaign activations with organic media momentum.',
  11: 'Apple Music Catalog Activity counts the releases — singles, EPs, albums — that landed on iTunes / Apple Music in the last 90 days. Apple\'s ecosystem skews older and more affluent than Spotify, so a strong cadence here signals reach into the demographics that drive premium pricing for sync, sponsorship, and tour. Pair with KPI 5 (Spotify Listener Trend) to detect platform-asymmetric breakouts.',
};

// ─── Formatters ───────────────────────────────────────────────────────────────

function fmtNumber(n: number | null): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

function fmtRecency(days: number): string {
  if (days === 0)   return 'today';
  if (days === 1)   return '1d ago';
  if (days <= 60)   return `${days}d ago`;
  if (days < 365)   return `${Math.round(days / 30)}mo ago`;
  return `${(days / 365).toFixed(1)}yr ago`;
}

function fmtValue(val: number | null, format: KpiMeta['format']): string {
  if (val == null) return '—';
  switch (format) {
    case 'number':   return fmtNumber(val);
    case 'percent':  return `${val.toFixed(2)}%`;
    case 'recency':  return fmtRecency(val);
    case 'posts':    return `${val}`;
    case 'ratio':    return `${(val * 100).toFixed(0)}%`;
    case 'articles': return `${val}`;
  }
}

function fmtDelta(pct: number | null): string {
  if (pct == null) return '';
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

// ─── Row data ─────────────────────────────────────────────────────────────────

interface LeaderRow {
  rank:           number;
  artistName:     string;
  artistSlug:     string;
  tier:           string;
  currentValue:   number | null;
  deltaPercent:   number | null;
  trend:          string;
  benchmarkTier:  string | null;
  alert:          string | null;
}

function buildRows(
  artists: SnapshotArtist[],
  kpiId:   number,
  asc:     boolean,
): LeaderRow[] {
  const rows: LeaderRow[] = [];

  for (const a of artists) {
    const kpi = a.kpis.find(k => k.kpi_id === kpiId);
    if (!kpi) continue;
    rows.push({
      rank:          0,
      artistName:    a.artist_name,
      artistSlug:    a.artist_slug,
      tier:          a.tier,
      currentValue:  kpi.current_value,
      deltaPercent:  kpi.delta_percent,
      trend:         kpi.trend,
      benchmarkTier: kpi.benchmark_tier,
      alert:         kpi.alert,
    });
  }

  rows.sort((a, b) => {
    const av = a.currentValue ?? (asc ? Infinity : -Infinity);
    const bv = b.currentValue ?? (asc ? Infinity : -Infinity);
    return asc ? av - bv : bv - av;
  });

  rows.forEach((r, i) => { r.rank = i + 1; });
  return rows.slice(0, 5);
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function TrendArrow({ trend }: { trend: string }) {
  if (trend === 'up')   return <span className="text-[var(--color-accent-up)]">▲</span>;
  if (trend === 'down') return <span className="text-[var(--color-accent-down)]">▼</span>;
  return <span className="text-[var(--color-text-muted)]">—</span>;
}

const TIER_DOT: Record<string, string> = {
  mega:     'bg-white',
  major:    'bg-[#999]',
  rising:   'bg-[#666]',
  emerging: 'bg-[#444]',
};

// ─── Main component ───────────────────────────────────────────────────────────

export interface KpiLeaderboardProps {
  kpiId:   number;
  artists: SnapshotArtist[];
  /** Override the displayed KPI name */
  title?:  string;
  /** How many rows to show (default 5) */
  limit?:  number;
}

export function KpiLeaderboard({ kpiId, artists, title, limit = 5 }: KpiLeaderboardProps) {
  const meta = KPI_META[kpiId];
  const [asc, setAsc] = useState(meta?.invertSort ?? false);

  if (!meta) return null;

  const rows = buildRows(artists, kpiId, asc).slice(0, limit);
  const displayTitle = title ?? meta.name;

  const showDelta = kpiId !== 6 && kpiId !== 7 && kpiId !== 9 && kpiId !== 10;

  const accentColor = KPI_COLOR[kpiId] ?? '#999';

  return (
    <div
      className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-sm overflow-hidden"
      style={{ borderTop: `2px solid ${accentColor}` }}
    >

      {/* Header */}
      <div className="px-4 pt-3 pb-3 border-b border-[var(--color-border)]">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div>
            <p
              className="font-[family-name:var(--font-mono)] text-[12px] tracking-[0.25em] uppercase font-bold"
              style={{ color: KPI_COLOR[kpiId] ?? '#999' }}
            >
              KPI {kpiId.toString().padStart(2, '0')}
            </p>
            <h3 className="font-[family-name:var(--font-ui)] font-bold text-[16px] text-[var(--color-text-primary)] leading-tight tracking-tight mt-0.5">
              {displayTitle}
            </h3>
          </div>

          {/* Sort toggle */}
          <button
            onClick={() => setAsc(a => !a)}
            className="flex-shrink-0 font-[family-name:var(--font-mono)] text-[13px] tracking-widest text-[var(--color-text-muted)] uppercase hover:text-[var(--color-text-secondary)] transition-colors duration-150 cursor-pointer"
            title={asc ? 'Sort descending' : 'Sort ascending'}
            aria-label={`Sort ${asc ? 'descending' : 'ascending'}`}
          >
            {asc ? '↑ ASC' : '↓ DESC'}
          </button>
        </div>

        {/* Business narrative */}
        {KPI_NARRATIVE[kpiId] && (
          <p className="text-[13px] text-[var(--color-text-secondary)] leading-relaxed font-[family-name:var(--font-ui)] mt-1">
            {KPI_NARRATIVE[kpiId]}
          </p>
        )}
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[16px_1fr_auto_auto] items-center gap-x-3 px-4 py-1.5 border-b border-[var(--color-border)]">
        <span className="font-[family-name:var(--font-mono)] text-[12px] tracking-widest text-[var(--color-text-muted)] uppercase">#</span>
        <span className="font-[family-name:var(--font-mono)] text-[12px] tracking-widest text-[var(--color-text-muted)] uppercase">Artist</span>
        {showDelta
          ? <span className="font-[family-name:var(--font-mono)] text-[8px] tracking-widest text-[var(--color-text-muted)] uppercase text-right">Δ</span>
          : <span />
        }
        <span className="font-[family-name:var(--font-mono)] text-[8px] tracking-widest text-[var(--color-text-muted)] uppercase text-right">
          {meta.shortName}
        </span>
      </div>

      {/* Rows */}
      {rows.map(row => (
        <div
          key={row.artistSlug}
          className="grid grid-cols-[16px_1fr_auto_auto] items-center gap-x-3 px-4 py-2.5 border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-bg-card-hover)] transition-colors duration-100"
        >
          {/* Rank */}
          <span className={[
            'font-[family-name:var(--font-mono)] text-[14px] tabular-nums',
            row.rank === 1 ? 'text-[var(--color-text-primary)]' : 'text-[var(--color-text-muted)]',
          ].join(' ')}>
            {row.rank}
          </span>

          {/* Artist name + tier dot */}
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className={[
                'flex-shrink-0 w-1.5 h-1.5 rounded-full',
                TIER_DOT[row.tier] ?? 'bg-[#444]',
              ].join(' ')}
              title={row.tier}
            />
            <span className="text-[15px] text-[var(--color-text-secondary)] truncate leading-tight">
              {row.artistName}
            </span>
            {row.alert && (
              <span className="flex-shrink-0 font-[family-name:var(--font-mono)] text-[12px] tracking-widest text-[var(--color-text-muted)] uppercase opacity-60">
                {row.alert.replace(/—.*/, '').trim()}
              </span>
            )}
          </div>

          {/* Delta % */}
          {showDelta
            ? (
              <div className="text-right">
                {row.deltaPercent !== null && Math.abs(row.deltaPercent) < 500 && (
                  <span className={[
                    'font-[family-name:var(--font-mono)] text-[14px] tabular-nums',
                    row.trend === 'up'   ? 'text-[var(--color-accent-up)]' :
                    row.trend === 'down' ? 'text-[var(--color-accent-down)]' :
                    'text-[var(--color-text-muted)]',
                  ].join(' ')}>
                    <TrendArrow trend={row.trend} />
                    {' '}{fmtDelta(row.deltaPercent)}
                  </span>
                )}
              </div>
            )
            : <div />
          }

          {/* Current value + benchmark */}
          <div className="text-right">
            <span
              className="font-[family-name:var(--font-mono)] text-[15px] tabular-nums whitespace-nowrap font-semibold"
              style={{ color: row.rank === 1 ? (KPI_COLOR[kpiId] ?? 'var(--color-text-primary)') : 'var(--color-text-primary)' }}
            >
              {fmtValue(row.currentValue, meta.format)}
            </span>
            {row.benchmarkTier && (
              <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] whitespace-nowrap">
                {row.benchmarkTier}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
