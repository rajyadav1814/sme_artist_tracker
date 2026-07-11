import { useState, useEffect } from 'react';
import type { RosterArtist, SnapshotArtist, KpiEntry, ArtistTier } from '../data/types';

// ─── Colour tokens ────────────────────────────────────────────────────────────
// All colours are intentional semantic signals — green = good/up, red = bad/down,
// amber = caution, tier colours differentiate artist level, KPI labels each have
// a distinct hue so rows are scannable at a glance.

const CLR = {
  up:        '#4ade80',  // green-400  — growth, positive trend
  down:      '#f87171',  // red-400    — decline, negative trend
  flat:      '#6b7280',  // gray-500   — no change

  mega:      '#fbbf24',  // amber-400  — superstar tier
  major:     '#60a5fa',  // blue-400   — regional powerhouse
  rising:    '#a78bfa',  // violet-400 — growing
  emerging:  '#34d399',  // emerald-400— early stage

  reach:     '#60a5fa',  // blue       — social reach label
  spotify:   '#4ade80',  // green      — streaming label
  engRate:   '#c084fc',  // purple-400 — engagement label
  release:   '#fbbf24',  // amber      — release recency label

  engExcellent: '#4ade80',  // >3.5%
  engGood:      '#a3e635',  // 1.5–3.5%  lime-400
  engAverage:   '#fbbf24',  // 0.5–1.5%
  engLow:       '#f87171',  // <0.5%

  fresh:    '#4ade80',   // 0–14 days
  recent:   '#fbbf24',   // 15–60 days
  aging:    '#fb923c',   // 61–180 days
  dark:     '#f87171',   // >180 days

  alertNeg: '#f87171',   // decline / going dark / freefall
  alertWarn:'#fbbf24',   // caution-type alerts
  alertPos: '#4ade80',   // breakout / positive
} as const;

// ─── KPI category colours (expanded panel) ────────────────────────────────────
const KPI_COLOR: Record<number, string> = {
  1:  CLR.reach,     // Total Social Reach
  2:  CLR.reach,     // Reach Velocity
  3:  CLR.engRate,   // Engagement Rate
  4:  CLR.spotify,   // Spotify Monthly Listeners
  5:  CLR.spotify,   // Spotify Listener Trend
  6:  '#22d3ee',     // Content Velocity    — cyan-400
  7:  '#2dd4bf',     // Platform Diversity  — teal-400
  8:  '#f472b6',     // Video View Momentum — pink-400
  9:  CLR.release,   // Release Recency
  10: '#fb923c',     // News & Press        — orange-400
};

// ─── Formatters ──────────────────────────────────────────────────────────────

function fmtNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

function fmtDelta(pct: number | null | undefined): string {
  if (pct == null) return '';
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

function fmtRecencyDays(days: number | null | undefined): string {
  if (days == null) return '—';
  if (days === 0)   return 'today';
  if (days === 1)   return '1d ago';
  if (days <= 60)   return `${days}d ago`;
  if (days < 365)   return `${Math.round(days / 30)}mo ago`;
  return `${(days / 365).toFixed(1)}yr ago`;
}

function recencyColor(days: number | null | undefined): string {
  if (days == null)  return '#6b7280';
  if (days <= 14)    return CLR.fresh;
  if (days <= 60)    return CLR.recent;
  if (days <= 180)   return CLR.aging;
  return CLR.dark;
}

function engColor(tier: string | null | undefined): string {
  if (!tier) return '#9ca3af';
  const t = tier.toLowerCase();
  if (t === 'excellent') return CLR.engExcellent;
  if (t === 'good')      return CLR.engGood;
  if (t === 'average')   return CLR.engAverage;
  if (t === 'low')       return CLR.engLow;
  return '#9ca3af';
}

function alertColors(label: string): { bg: string; text: string; border: string } {
  const l = label.toLowerCase();
  const isNeg = l.includes('dark') || l.includes('decline') || l.includes('freefall') || l.includes('silence');
  const isWarn = l.includes('caution') || l.includes('overdue') || l.includes('aging');
  if (isNeg)  return { bg: 'rgba(248,113,113,0.12)', text: CLR.alertNeg, border: 'rgba(248,113,113,0.4)' };
  if (isWarn) return { bg: 'rgba(251,191,36,0.12)',  text: CLR.alertWarn, border: 'rgba(251,191,36,0.4)' };
  return       { bg: 'rgba(74,222,128,0.12)',         text: CLR.alertPos,  border: 'rgba(74,222,128,0.4)'  };
}

// ─── Narrative interpreter ────────────────────────────────────────────────────
// Generates a 15–30 word business-language interpretation of the artist's KPI
// snapshot, focusing on the most actionable signal available.

function buildNarrative(snapshot: SnapshotArtist): string {
  const kpi = Object.fromEntries(snapshot.kpis.map(k => [k.kpi_id, k]));
  const vel      = kpi[2];
  const eng      = kpi[3];
  const spTrend  = kpi[5];
  const recency  = kpi[9];
  const press    = kpi[10];

  const velPct   = vel?.current_value   ?? 0;
  const spPct    = spTrend?.current_value ?? 0;
  const engTier  = (eng?.benchmark_tier ?? '').toLowerCase();
  const recDays  = recency?.current_value ?? 999;
  const pressN   = press?.current_value  ?? 0;
  const tier     = snapshot.tier;

  // Strong growth momentum
  if (velPct >= 2 && spPct >= 2) {
    return `Dual momentum: social reach and streaming both accelerating. Prioritize marketing spend — the audience is primed for a major campaign.`;
  }
  if (velPct >= 2) {
    return `Social audience growing rapidly. Strong window for brand partnerships and content amplification to capitalise on rising visibility.`;
  }
  if (spPct >= 5) {
    return `Spotify listeners surging. Lean into playlist pitching and editorial outreach now while streaming momentum is at its peak.`;
  }

  // Decline signals
  if (velPct <= -2 && recDays > 120) {
    return `Declining reach with no recent release. Schedule A&R check-in — artist may need content strategy intervention to reverse audience attrition.`;
  }
  if (spPct <= -5) {
    return `Spotify listeners dropping sharply. Investigate post-release decay or playlist removal; a new single could stabilise streaming performance.`;
  }

  // Engagement quality
  if (engTier === 'excellent' && (tier === 'rising' || tier === 'emerging')) {
    return `Exceptional engagement for their audience size — highly loyal fanbase. Ideal candidate for direct-to-fan campaigns and merchandise activations.`;
  }
  if (engTier === 'low' && (tier === 'mega' || tier === 'major')) {
    return `Audience size is large but engagement is weak, signalling passive fandom. Invest in interactive content and community-building to deepen connection.`;
  }

  // Release recency
  if (recDays <= 14) {
    return `New release in active window. Maximise DSP promotion, sync placements, and press coverage while first-week streaming momentum is highest.`;
  }
  if (recDays > 180) {
    return `No new music in over six months. Release pipeline urgency is high — audience retention risk increases significantly beyond the 180-day mark.`;
  }

  // Press buzz
  if (pressN >= 10) {
    return `High press momentum this week. Amplify PR activity with social content and partner placements to convert media attention into streaming gains.`;
  }

  // Tier-contextual steady state
  if (tier === 'mega') {
    return `Performing at expected Mega-tier baseline. Monitor for relative shifts; even modest velocity changes represent significant absolute audience movement.`;
  }
  if (tier === 'major') {
    return `Stable Major-tier performance. Target specific KPI improvements — an engagement or streaming push could trigger breakthrough to Mega status.`;
  }
  if (tier === 'rising') {
    return `Rising-tier artist holding steady. Consistent content output and a new release could accelerate the trajectory toward Major-tier reach.`;
  }
  return `Emerging artist with a developing baseline. Focus on platform consistency and a strong debut release to establish measurable momentum.`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function TrendArrow({ trend }: { trend: string }) {
  if (trend === 'up')   return <span style={{ color: CLR.up }}>▲</span>;
  if (trend === 'down') return <span style={{ color: CLR.down }}>▼</span>;
  return <span style={{ color: CLR.flat }}>—</span>;
}

function AlertBadge({ label }: { label: string }) {
  const { bg, text, border } = alertColors(label);
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded-sm font-[family-name:var(--font-mono)] text-[13px] tracking-widest uppercase"
      style={{ background: bg, color: text, border: `1px solid ${border}` }}
    >
      {label.replace(/—.*/, '').trim()}
    </span>
  );
}

const TIER_LABEL: Record<ArtistTier, string> = {
  mega:     'MEGA',
  major:    'MAJOR',
  rising:   'RISING',
  emerging: 'EMERGING',
};

const TIER_COLOR: Record<ArtistTier, string> = {
  mega:     CLR.mega,
  major:    CLR.major,
  rising:   CLR.rising,
  emerging: CLR.emerging,
};

// ─── Apple Music detail panel (rendered below KPI list when expanded) ───────

interface AppleSong { title?: string; album?: string; release_date?: string }
interface AppleLatestRelease { title?: string; date?: string; type?: string }

function AppleMusicPanel({ kpi11 }: { kpi11: KpiEntry | undefined }) {
  if (!kpi11) return null;
  const latest    = (kpi11.latest_release as AppleLatestRelease | undefined) ?? undefined;
  const topSongs  = (kpi11.top_songs as AppleSong[] | undefined) ?? [];
  const totalAlbums = kpi11.total_albums as number | null | undefined;
  const genre       = kpi11.primary_genre as string | null | undefined;

  // If we have nothing to show, hide the panel entirely
  if (!latest?.title && topSongs.length === 0 && !totalAlbums) return null;

  return (
    <div className="mt-4 pt-3 border-t border-[var(--color-border)]">
      <p className="font-[family-name:var(--font-mono)] text-[13px] tracking-[0.2em] text-[var(--color-text-muted)] uppercase mb-2">
        Apple Music
        {genre && (
          <span className="ml-2 text-[var(--color-text-muted)] opacity-60 normal-case tracking-normal">
            · {genre}
          </span>
        )}
      </p>

      {latest?.title && (
        <div className="mb-3">
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-widest text-[var(--color-text-muted)] uppercase">
            Latest release
          </p>
          <p className="text-[14px] text-[var(--color-text-primary)] leading-tight mt-0.5">
            {latest.title}
          </p>
          <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] mt-0.5">
            {latest.date ?? '—'}
            {latest.type && <span className="opacity-60 ml-2">· {latest.type}</span>}
            {totalAlbums != null && (
              <span className="opacity-60 ml-3">{totalAlbums} albums in catalog</span>
            )}
          </p>
        </div>
      )}

      {topSongs.length > 0 && (
        <div>
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-widest text-[var(--color-text-muted)] uppercase mb-1">
            Top songs
          </p>
          <ol className="space-y-0.5">
            {topSongs.slice(0, 5).map((s, i) => (
              <li
                key={`${s.title}-${i}`}
                className="flex items-baseline gap-3 font-[family-name:var(--font-mono)] text-[13px]"
              >
                <span className="text-[var(--color-text-muted)] tabular-nums w-4">{i + 1}</span>
                <span className="text-[var(--color-text-primary)] truncate flex-1">
                  {s.title ?? '—'}
                </span>
                {s.album && (
                  <span className="text-[var(--color-text-muted)] truncate text-[12px] opacity-70">
                    {s.album}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}


// ─── KPI row in expanded panel ───────────────────────────────────────────────

function KpiRow({ kpi }: { kpi: KpiEntry }) {
  const showPct = kpi.delta_percent !== null && Math.abs(kpi.delta_percent) < 500;
  const labelColor = KPI_COLOR[kpi.kpi_id] ?? '#9ca3af';

  const v = kpi.current_value;
  let displayValue: string;
  if (v == null) {
    displayValue = '—';
  } else {
    switch (kpi.kpi_id) {
      case 1:  displayValue = fmtNumber(v); break;
      case 2:  displayValue = `${v.toFixed(2)}%`; break;
      case 3:  displayValue = `${v.toFixed(2)}%`; break;
      case 4:  displayValue = fmtNumber(v); break;
      case 5:  displayValue = `${v.toFixed(2)}%`; break;
      case 6:  displayValue = `${v} posts/wk`; break;
      case 7:  displayValue = `${(v * 100).toFixed(0)}%`; break;
      case 8:  displayValue = fmtNumber(v); break;
      case 9:  displayValue = fmtRecencyDays(v); break;
      case 10: displayValue = `${v} articles`; break;
      default: displayValue = v.toString();
    }
  }

  // Value colour: recency and engagement get semantic colours; others white
  let valueColor = '#ffffff';
  if (kpi.kpi_id === 9)  valueColor = recencyColor(v);
  if (kpi.kpi_id === 3)  valueColor = engColor(kpi.benchmark_tier);
  if (kpi.kpi_id === 2 || kpi.kpi_id === 5) {
    if (kpi.trend === 'up')   valueColor = CLR.up;
    if (kpi.trend === 'down') valueColor = CLR.down;
  }

  return (
    <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-3 py-2.5 border-b border-[var(--color-border)] last:border-0">
      {/* Name + alert */}
      <div>
        <p
          className="text-[15px] leading-tight font-medium"
          style={{ color: labelColor }}
        >
          {kpi.kpi_name}
        </p>
        {kpi.alert && <AlertBadge label={kpi.alert} />}
      </div>

      {/* Delta */}
      <div className="text-right">
        {showPct && kpi.delta_percent !== null && (
          <span
            className="font-[family-name:var(--font-mono)] text-[14px]"
            style={{ color: kpi.trend === 'up' ? CLR.up : kpi.trend === 'down' ? CLR.down : CLR.flat }}
          >
            <TrendArrow trend={kpi.trend} /> {fmtDelta(kpi.delta_percent)}
          </span>
        )}
      </div>

      {/* Value */}
      <div
        className="font-[family-name:var(--font-mono)] text-[15px] text-right whitespace-nowrap font-semibold"
        style={{ color: valueColor }}
      >
        {displayValue}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export interface ArtistCardProps {
  artist:             RosterArtist;
  snapshot:           SnapshotArtist;
  /** When true, the card opens with KPIs visible. Used by the roster search:
   *  if a search narrows the grid to a single artist, that card auto-expands.
   *  The user can still toggle expand/collapse manually after the prop fires. */
  initiallyExpanded?: boolean;
}

export function ArtistCard({ artist, snapshot, initiallyExpanded = false }: ArtistCardProps) {
  const [expanded, setExpanded] = useState(initiallyExpanded);

  // Sync with prop changes so search-driven auto-expand reacts in real time
  useEffect(() => { setExpanded(initiallyExpanded); }, [initiallyExpanded]);

  const kpi = Object.fromEntries(snapshot.kpis.map(k => [k.kpi_id, k])) as Record<number, KpiEntry>;

  const reach      = kpi[1];
  const velocity   = kpi[2];
  const engagement = kpi[3];
  const spotify    = kpi[4];
  const recency    = kpi[9];

  const alerts = snapshot.kpis
    .filter((k): k is KpiEntry & { alert: string } => k.alert !== null)
    .map(k => ({ id: k.kpi_id, label: k.alert }));

  const tierColor = TIER_COLOR[snapshot.tier];

  const velColor = velocity.trend === 'up' ? CLR.up : velocity.trend === 'down' ? CLR.down : CLR.flat;
  const spTrColor = spotify.trend === 'up' ? CLR.up : spotify.trend === 'down' ? CLR.down : CLR.flat;

  return (
    <article
      className={[
        'group relative flex flex-col overflow-hidden',
        'bg-[var(--color-bg-card)] border border-[var(--color-border)]',
        'rounded-sm cursor-pointer select-none',
        'transition-all duration-300 ease-out',
        'hover:bg-[var(--color-bg-card-hover)] hover:border-[var(--color-border-light)]',
        'hover:scale-[1.02] hover:shadow-[0_16px_48px_rgba(0,0,0,0.8)]',
        "before:content-[''] before:absolute before:inset-x-0 before:top-0 before:h-[2px]",
        'before:scale-x-0 before:origin-left',
        'before:transition-transform before:duration-300 before:ease-out',
        'group-hover:before:scale-x-100',
        expanded ? 'shadow-[0_0_0_1px_var(--color-border-light)]' : '',
      ].join(' ')}
      style={{ ['--tw-before-bg' as string]: tierColor }}
      onClick={() => setExpanded(e => !e)}
      role="button"
      aria-expanded={expanded}
      aria-label={`${artist.name} artist card`}
    >
      {/* Tier-coloured top sweep line rendered via pseudo-el workaround */}
      <div
        className="absolute inset-x-0 top-0 h-[2px] scale-x-0 origin-left group-hover:scale-x-100 transition-transform duration-300 ease-out"
        style={{ background: tierColor }}
      />

      {/* ── Avatar ─────────────────────────────────────────────────── */}
      <div className="flex justify-center pt-6 pb-4 relative">
        <div className="relative">
          <img
            src={artist.image_url}
            alt={artist.name}
            width={192}
            height={192}
            className={[
              'w-[192px] h-[192px] rounded-full object-cover',
              'border-2',
              'grayscale transition-all duration-500 ease-out',
              'group-hover:grayscale-0',
              'group-hover:shadow-[0_0_32px_rgba(255,255,255,0.1)]',
            ].join(' ')}
            style={{ borderColor: `${tierColor}55` }}
            onError={e => {
              e.currentTarget.src =
                `https://placehold.co/192x192/1A1A1A/444444?text=${encodeURIComponent(artist.slug)}`;
            }}
          />

          {/* Tier dot — top-right, coloured by tier */}
          <span
            className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full border-2 border-[var(--color-bg-card)]"
            style={{ background: tierColor }}
            title={`${snapshot.tier} tier`}
          />
        </div>
      </div>

      {/* ── Identity ───────────────────────────────────────────────── */}
      <div className="px-4 pb-3 text-center">
        <h3 className="font-[family-name:var(--font-headline)] font-black text-[17px] leading-tight text-[var(--color-text-primary)] tracking-tight">
          {artist.name}
        </h3>
        <p className="mt-1 font-[family-name:var(--font-mono)] text-[13px] tracking-[0.2em] uppercase">
          <span style={{ color: tierColor }} className="font-bold">
            {TIER_LABEL[snapshot.tier]}
          </span>
          <span className="mx-1.5 opacity-30 text-[var(--color-text-muted)]">·</span>
          <span className="text-[var(--color-text-muted)]">{fmtNumber(reach.current_value)}</span>
        </p>
        {/* Narrative interpretation — business action takeaway */}
        <p
          className="mt-2.5 mx-1 text-[13px] leading-snug font-[family-name:var(--font-ui)] italic text-white"
        >
          {buildNarrative(snapshot)}
        </p>
      </div>

      {/* ── Divider ────────────────────────────────────────────────── */}
      <div className="mx-4 border-t border-[var(--color-border)]" />

      {/* ── KPI summary ────────────────────────────────────────────── */}
      <div className="px-4 py-3 space-y-2.5">

        {/* Total Reach + velocity */}
        <div className="flex items-baseline justify-between gap-2">
          <span
            className="font-[family-name:var(--font-mono)] text-[13px] uppercase tracking-widest flex-shrink-0"
            style={{ color: CLR.reach }}
          >
            Reach
          </span>
          <span className="font-[family-name:var(--font-mono)] text-[16px] text-[var(--color-text-primary)] text-right">
            {fmtNumber(reach.current_value)}
            {velocity.current_value != null && (
              <span className="ml-1.5 text-[14px]" style={{ color: velColor }}>
                <TrendArrow trend={velocity.trend} /> {fmtDelta(velocity.current_value)}
              </span>
            )}
          </span>
        </div>

        {/* Spotify Listeners */}
        <div className="flex items-baseline justify-between gap-2">
          <span
            className="font-[family-name:var(--font-mono)] text-[13px] uppercase tracking-widest flex-shrink-0"
            style={{ color: CLR.spotify }}
          >
            Spotify
          </span>
          <span className="font-[family-name:var(--font-mono)] text-[16px] text-[var(--color-text-primary)] text-right">
            {fmtNumber(spotify.current_value)}
            <span className="ml-1.5 text-[14px]" style={{ color: spTrColor }}>
              <TrendArrow trend={spotify.trend} />
            </span>
          </span>
        </div>

        {/* Engagement Rate */}
        <div className="flex items-baseline justify-between gap-2">
          <span
            className="font-[family-name:var(--font-mono)] text-[13px] uppercase tracking-widest flex-shrink-0"
            style={{ color: CLR.engRate }}
          >
            Eng. Rate
          </span>
          <span className="font-[family-name:var(--font-mono)] text-[16px] text-right">
            <span style={{ color: engColor(engagement.benchmark_tier) }}>
              {engagement.current_value != null ? `${engagement.current_value.toFixed(2)}%` : '—'}
            </span>
            {engagement.benchmark_tier && (
              <span className="ml-1.5 text-[13px] text-[var(--color-text-muted)]">
                {engagement.benchmark_tier}
              </span>
            )}
          </span>
        </div>

        {/* Release recency */}
        <div className="flex items-baseline justify-between gap-2">
          <span
            className="font-[family-name:var(--font-mono)] text-[13px] uppercase tracking-widest flex-shrink-0"
            style={{ color: CLR.release }}
          >
            Release
          </span>
          <span
            className="font-[family-name:var(--font-mono)] text-[15px] font-semibold"
            style={{ color: recencyColor(recency.current_value) }}
          >
            {fmtRecencyDays(recency.current_value)}
          </span>
        </div>
      </div>

      {/* ── Alert badges ───────────────────────────────────────────── */}
      {alerts.length > 0 && (
        <>
          <div className="mx-4 border-t border-[var(--color-border)]" />
          <div className="px-4 py-2.5 flex flex-wrap gap-1.5">
            {alerts.map(({ id, label }) => (
              <AlertBadge key={id} label={label} />
            ))}
          </div>
        </>
      )}

      {/* ── Expanded KPI panel ─────────────────────────────────────── */}
      {expanded && (
        <div
          className="mx-4 mb-4 mt-1"
          onClick={e => e.stopPropagation()}
        >
          <div className="border-t border-[var(--color-border)] pt-3">
            <p className="font-[family-name:var(--font-mono)] text-[13px] tracking-[0.2em] text-[var(--color-text-muted)] uppercase mb-3">
              All KPIs · {new Date().toISOString().slice(0, 10)}
            </p>
            {snapshot.kpis.map(k => (
              <KpiRow key={k.kpi_id} kpi={k} />
            ))}
            <AppleMusicPanel kpi11={snapshot.kpis.find(k => k.kpi_id === 11)} />
          </div>
        </div>
      )}

      {/* ── Expand toggle hint ─────────────────────────────────────── */}
      <div className="mt-auto px-4 pb-3 pt-1 flex justify-center">
        <span
          className="font-[family-name:var(--font-mono)] text-[13px] tracking-widest uppercase opacity-0 group-hover:opacity-100 transition-opacity duration-200"
          style={{ color: tierColor }}
        >
          {expanded ? '↑ Collapse' : '↓ All KPIs'}
        </span>
      </div>
    </article>
  );
}
