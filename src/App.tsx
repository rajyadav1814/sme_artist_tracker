import { useState, type ReactNode } from 'react';
import { roster, snapshot, briefing } from './data/loader';
import { ArtistCard }     from './components/artist-card';
import { NewsItem }       from './components/news-item';
import { KpiLeaderboard } from './components/kpi-leaderboard';
import { SmlLogo }        from './components/sml-logo';
import { ChatAgent }      from './components/chat-agent';
import { AnalystPage }    from './components/analyst-page';
import { ThemeToggle, useTheme } from './components/theme-toggle';
import { buildSystemPrompt } from './lib/ai-utils';

type Tab = 'overview' | 'stories' | 'roster' | 'leaderboards' | 'analyst';

// Pre-built once — roster/snapshot/briefing are module-level constants
const systemPrompt = buildSystemPrompt(roster, snapshot, briefing);
const apiKey = (import.meta.env.VITE_ANTHROPIC_API_KEY as string | undefined) ?? '';

const snapshotBySlug = Object.fromEntries(
  snapshot.artists.map(a => [a.artist_slug, a])
);
const imageBySlug = Object.fromEntries(
  roster.artists.map(a => [a.slug, a.image_url])
);

// ── Animation helpers ─────────────────────────────────────────────────────────

function FadeUp({
  index = 0,
  baseDelay = 0,
  children,
}: {
  index?:     number;
  baseDelay?: number;
  children:   ReactNode;
}) {
  return (
    <div
      className="anim-fade-up"
      style={{ animationDelay: `${baseDelay + Math.min(index * 35, 900)}ms` }}
    >
      {children}
    </div>
  );
}

// ── Shared layout primitives ──────────────────────────────────────────────────

function SectionLabel({ label, meta }: { label: string; meta?: string }) {
  return (
    <div className="flex items-baseline gap-3 mb-6">
      <h2 className="font-[family-name:var(--font-headline)] font-black text-2xl text-[var(--color-text-primary)] tracking-tight">
        {label}
      </h2>
      {meta && (
        <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] uppercase tracking-widest">
          {meta}
        </span>
      )}
    </div>
  );
}

function Divider() {
  return <div className="border-t border-[var(--color-border)] my-12" />;
}

// ── Tab Navigation ────────────────────────────────────────────────────────────

function TabNav({ active, onSelect }: { active: Tab; onSelect: (t: Tab) => void }) {
  // Each tab has a distinct accent colour so they stand out while scrolling.
  // Order: daily briefing first, reference/help last.
  const tabs: { id: Tab; label: string; count?: string; color: string; activeBg: string }[] = [
    { id: 'stories',      label: 'Top Stories',     color: '#f472b6', activeBg: 'rgba(244,114,182,0.18)', count: briefing.items.length.toString() }, // pink
    { id: 'roster',       label: 'Artist Roster',   color: '#60a5fa', activeBg: 'rgba(96,165,250,0.18)',  count: roster.artist_count.toString() },    // blue
    { id: 'leaderboards', label: 'KPI Leaderboards',color: '#fbbf24', activeBg: 'rgba(251,191,36,0.18)',  count: '11' },                               // amber
    { id: 'analyst',      label: 'AI Analyst',      color: '#4ade80', activeBg: 'rgba(74,222,128,0.18)'  },                                            // green
    { id: 'overview',     label: 'Overview',        color: '#a78bfa', activeBg: 'rgba(167,139,250,0.18)' }, // violet
  ];

  return (
    <nav className="mb-10 anim-fade-in">
      <div className="flex flex-wrap gap-2">
        {tabs.map(tab => {
          const isActive = active === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onSelect(tab.id)}
              className={[
                'relative flex items-center gap-2 px-5 py-3',
                'font-[family-name:var(--font-mono)] text-[13px] tracking-widest uppercase font-bold',
                'rounded-sm border-2 transition-all duration-200 cursor-pointer',
              ].join(' ')}
              style={{
                borderColor: isActive ? tab.color : `${tab.color}44`,
                background:  isActive ? tab.activeBg : 'transparent',
                color:       isActive ? tab.color : `${tab.color}88`,
                boxShadow:   isActive ? `0 0 12px ${tab.color}22` : 'none',
              }}
            >
              {tab.label}
              {tab.count !== undefined && (
                <span
                  className="font-[family-name:var(--font-mono)] text-[11px] px-1.5 py-0.5 rounded-sm font-bold"
                  style={{
                    background: isActive ? tab.color : `${tab.color}22`,
                    color:      isActive ? 'var(--color-bg-primary)' : tab.color,
                  }}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className="border-t border-[var(--color-border)] mt-3" />
    </nav>
  );
}

// ── Overview page ─────────────────────────────────────────────────────────────

function OverviewCard({
  icon, title, children,
}: { icon: string; title: string; children: ReactNode }) {
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-sm p-6">
      <div className="flex items-center gap-3 mb-4">
        <span className="font-[family-name:var(--font-headline)] text-2xl text-[var(--color-text-primary)]">
          {icon}
        </span>
        <h3 className="font-[family-name:var(--font-headline)] font-black text-[17px] text-[var(--color-text-primary)] tracking-tight">
          {title}
        </h3>
      </div>
      <div className="font-[family-name:var(--font-ui)] text-[14px] text-[var(--color-text-secondary)] leading-relaxed space-y-2">
        {children}
      </div>
    </div>
  );
}

function KpiQuickRef() {
  const kpis = [
    { id: '01', name: 'Total Social Reach',          desc: 'Sum of followers across all platforms — raw audience size and label leverage.' },
    { id: '02', name: 'Reach Velocity',              desc: '% change in total reach vs. prior snapshot — early signal of a breakout or decline.' },
    { id: '03', name: 'Engagement Rate',             desc: 'Likes + comments on recent posts ÷ total followers — quality of audience connection.' },
    { id: '04', name: 'Spotify Monthly Listeners',   desc: "Industry's standard streaming power metric, pulled directly from Spotify." },
    { id: '05', name: 'Spotify Listener Trend',      desc: '% change in monthly listeners — measures release impact and streaming momentum.' },
    { id: '06', name: 'Content Velocity',            desc: 'Posts published across all platforms in the last 7 days — artist activity level.' },
    { id: '07', name: 'Platform Diversity',          desc: 'Active platforms ÷ total platforms — flags single-platform dependency risk.' },
    { id: '08', name: 'YouTube Weekly Velocity',     desc: 'Average views across the 5 most recent YouTube videos — visual content performance and algorithmic push.' },
    { id: '09', name: 'Release Recency',             desc: 'Days since last release on Spotify or Apple Music — flags artists going dark on new material.' },
    { id: '10', name: 'News & Press Mentions',       desc: 'Unique articles mentioning the artist in the last 7 days — cultural relevance signal.' },
    { id: '11', name: 'Apple Music Catalog Activity',desc: 'Count of singles / EPs / albums on iTunes in the last 90 days — release cadence on Apple\'s platform.' },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
      {kpis.map(k => (
        <div key={k.id} className="flex gap-3 items-start">
          <span className="flex-shrink-0 font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-text-muted)] mt-0.5">
            {k.id}
          </span>
          <div>
            <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-primary)] tracking-wide">
              {k.name}
            </p>
            <p className="text-[13px] text-[var(--color-text-muted)] leading-snug mt-0.5">
              {k.desc}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

function Overview() {
  const alertCount = snapshot.artists.reduce(
    (n, a) => n + a.kpis.filter(k => k.alert !== null).length, 0
  );

  return (
    <div className="space-y-10">

      {/* Hero intro */}
      <FadeUp baseDelay={0}>
        <div className="border border-[var(--color-border)] rounded-sm p-8 bg-[var(--color-bg-secondary)]">
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.3em] text-[var(--color-text-muted)] uppercase mb-3">
            What is this?
          </p>
          <h2
            className="font-[family-name:var(--font-headline)] font-black text-[var(--color-text-primary)] leading-tight tracking-tight mb-4"
            style={{ fontSize: 'clamp(1.5rem, 3vw, 2.5rem)' }}
          >
            Your daily intelligence briefing<br />for the Sony Music Latin roster.
          </h2>
          <p className="text-[15px] text-[var(--color-text-secondary)] leading-relaxed max-w-3xl">
            Sony Latin Pulse runs a daily data pipeline that harvests social metrics, streaming numbers,
            and press mentions for every artist on the roster. It computes 11 KPIs per artist,
            detects significant changes, and surfaces the most newsworthy developments — all styled
            as a monochrome editorial newsroom.
          </p>

          {/* Stat row */}
          <div className="flex flex-wrap gap-8 mt-6 pt-6 border-t border-[var(--color-border)]">
            {([
              ['Artists tracked',    roster.artist_count.toString()],
              ['KPIs per artist',    '11'],
              ['Active alerts',      alertCount.toString()],
              ['Stories today',      briefing.items.length.toString()],
              ['Data as of',         snapshot.snapshot_date],
            ] as [string, string][]).map(([label, val]) => (
              <div key={label}>
                <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-widest text-[var(--color-text-muted)] uppercase">
                  {label}
                </p>
                <p className="font-[family-name:var(--font-mono)] text-[18px] text-[var(--color-text-primary)] mt-0.5">
                  {val}
                </p>
              </div>
            ))}
          </div>
        </div>
      </FadeUp>

      {/* How to use cards */}
      <FadeUp baseDelay={100}>
        <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.3em] text-[var(--color-text-muted)] uppercase mb-4">
          How to use this app
        </p>
      </FadeUp>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        <FadeUp baseDelay={150}>
          <OverviewCard icon="01" title="Top Stories">
            <p>
              The <strong className="text-[var(--color-text-primary)]">Top Stories</strong> tab shows
              today's most newsworthy developments across the roster, ranked by significance score.
            </p>
            <p>
              Each story card shows the artist image, a signal type badge (e.g. <em>MILESTONE</em>,{' '}
              <em>VIRAL</em>, <em>NEW RELEASE</em>), headline, KPI impact, and a 2–3 sentence editorial
              summary written by the AI news desk.
            </p>
            <p>
              Stories are scored using a weighted rubric — milestone crossings score highest (10),
              new releases and chart entries follow (9), then viral spikes and collaborations (8).
            </p>
          </OverviewCard>
        </FadeUp>

        <FadeUp baseDelay={200}>
          <OverviewCard icon="02" title="Artist Roster">
            <p>
              The <strong className="text-[var(--color-text-primary)]">Artist Roster</strong> tab
              shows every artist as a card with their photo, tier, and 4 headline KPIs at a glance.
            </p>
            <p>
              <strong className="text-[var(--color-text-primary)]">Click any card</strong> to expand
              all 11 KPIs with current values, trend arrows (▲ up / ▼ down), and percentage deltas
              versus the previous snapshot.
            </p>
            <p>
              Artist images are grayscale by default —{' '}
              <strong className="text-[var(--color-text-primary)]">hover</strong> any image to reveal
              color. Tier dots (white = Mega, gray = Major, dark = Rising/Emerging) appear
              top-right of each photo.
            </p>
          </OverviewCard>
        </FadeUp>

        <FadeUp baseDelay={250}>
          <OverviewCard icon="03" title="KPI Leaderboards">
            <p>
              The <strong className="text-[var(--color-text-primary)]">KPI Leaderboards</strong> tab
              ranks the top 5 artists for each of the 11 KPIs side-by-side.
            </p>
            <p>
              Use the <strong className="text-[var(--color-text-primary)]">↓ DESC / ↑ ASC</strong>{' '}
              toggle on any leaderboard to flip the sort direction — useful for spotting artists
              at the bottom of a metric (e.g. longest release gap, lowest engagement rate).
            </p>
            <p>
              Delta percentages (Δ column) show the change since the last snapshot. Trend arrows
              color-code each movement: white = up, gray = down, dash = flat.
            </p>
          </OverviewCard>
        </FadeUp>

        <FadeUp baseDelay={300}>
          <OverviewCard icon="04" title="News Ticker">
            <p>
              The <strong className="text-[var(--color-text-primary)]">scrolling ticker</strong>{' '}
              beneath the masthead always shows the current day's headlines — one per story,
              in priority order, looping continuously.
            </p>
            <p>
              The ticker is present on every tab so you never lose sight of today's most
              important movements while browsing the roster or leaderboards.
            </p>
          </OverviewCard>
        </FadeUp>
      </div>

      {/* KPI reference */}
      <FadeUp baseDelay={350}>
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-sm p-6">
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.3em] text-[var(--color-text-muted)] uppercase mb-2">
            KPI Reference
          </p>
          <h3 className="font-[family-name:var(--font-headline)] font-black text-[17px] text-[var(--color-text-primary)] mb-4">
            The 11 tracked metrics — what each one means
          </h3>
          <KpiQuickRef />
        </div>
      </FadeUp>

      {/* Alert tiers */}
      <FadeUp baseDelay={400}>
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-sm p-6">
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.3em] text-[var(--color-text-muted)] uppercase mb-2">
            Reading the badges
          </p>
          <h3 className="font-[family-name:var(--font-headline)] font-black text-[17px] text-[var(--color-text-primary)] mb-4">
            Alert labels and artist tiers
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
            <div>
              <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-secondary)] uppercase tracking-widest mb-3">
                Artist Tiers
              </p>
              <div className="space-y-2">
                {([
                  ['●', 'white',   'Mega',     '>50M total reach — global superstar'],
                  ['●', '#999',    'Major',    '10M–50M reach — regional powerhouse'],
                  ['●', '#666',    'Rising',   '1M–10M reach — growing momentum'],
                  ['●', '#444',    'Emerging', '<1M reach — early-stage artist'],
                ] as [string, string, string, string][]).map(([dot, color, tier, desc]) => (
                  <div key={tier} className="flex items-start gap-3">
                    <span style={{ color }} className="text-[16px] leading-none mt-0.5 flex-shrink-0">{dot}</span>
                    <div>
                      <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-primary)]">{tier}</span>
                      <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] ml-2">{desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-secondary)] uppercase tracking-widest mb-3">
                Data Confidence
              </p>
              <div className="space-y-2">
                {([
                  ['●●●●●', 'Verified',  'Direct from platform, fetched today'],
                  ['●●●●○', 'Recent',    'From aggregator or search, <48h old'],
                  ['●●●○○', 'Estimated', 'Multiple sources averaged, <7 days'],
                  ['●●○○○', 'Stale',     'Best available data, >7 days old'],
                  ['●○○○○', 'Inferred',  'Derived from indirect signals'],
                ] as [string, string, string][]).map(([dots, label, desc]) => (
                  <div key={label} className="flex items-start gap-3">
                    <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-secondary)] flex-shrink-0 mt-0.5">
                      {dots}
                    </span>
                    <div>
                      <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-primary)]">{label}</span>
                      <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] ml-2">{desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </FadeUp>

    </div>
  );
}

// ── Sections ──────────────────────────────────────────────────────────────────

function Masthead({ theme, onToggleTheme }: { theme: string; onToggleTheme: () => void }) {
  const alertCount = snapshot.artists.reduce(
    (n, a) => n + a.kpis.filter(k => k.alert !== null).length, 0
  );

  return (
    <header className="anim-fade-in">
      {/* Logo bar — sits above the editorial rule */}
      <div className="flex items-center justify-between mb-5">
        <SmlLogo className="h-[34px] w-auto opacity-90" />
        <ThemeToggle theme={theme as 'dark' | 'light'} onToggle={onToggleTheme} />
      </div>

      {/* Top rule — double-weight editorial line */}
      <div className="border-t-2 border-[var(--color-text-primary)] mb-4" />

      {/* Eyebrow: studio name left, date + cursor right */}
      <div className="flex items-center justify-between mb-3">
        <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.35em] text-[var(--color-text-muted)] uppercase">
          Sony Music Latin · Artist Intelligence
        </p>
        <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.2em] text-[var(--color-text-muted)] uppercase">
          {snapshot.snapshot_date}
          {/* blinking terminal cursor */}
          <span
            className="ml-1 text-[var(--color-text-muted)]"
            style={{ animation: 'blink 1.1s step-end infinite' }}
          >▌</span>
        </p>
      </div>

      {/* Masthead wordmark */}
      <h1
        className="font-[family-name:var(--font-headline)] font-black leading-none tracking-tight text-[var(--color-text-primary)]"
        style={{ fontSize: 'clamp(1.75rem, 4vw, 3.5rem)' }}
      >
        SONY MUSIC LATIN PULSE
      </h1>

      {/* Rule + "DAILY BRIEFING" centred label */}
      <div className="flex items-center gap-4 mt-3 mb-4">
        <div className="flex-1 border-t border-[var(--color-border)]" />
        <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.35em] text-[var(--color-text-muted)] uppercase whitespace-nowrap">
          Daily Briefing
        </p>
        <div className="flex-1 border-t border-[var(--color-border)]" />
      </div>

      {/* Stats bar */}
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        {([
        ] as [string, string][]).map(([label, val]) => (
          <div key={label} className="flex items-baseline gap-1.5">
            <span className="font-[family-name:var(--font-mono)] text-[11px] tracking-widest text-[var(--color-text-muted)] uppercase">
              {label}
            </span>
            <span className="font-[family-name:var(--font-mono)] text-[13px] text-[var(--color-text-secondary)]">
              {val}
            </span>
          </div>
        ))}
      </div>

      <div className="border-t border-[var(--color-border)] mt-4" />
    </header>
  );
}

// Signal-type accent colours for the ticker badges
const TICKER_SIGNAL_COLOR: Record<string, string> = {
  milestone:                 '#fbbf24',
  new_release:               '#4ade80',
  chart_movement:            '#4ade80',
  rapid_follower_surge:      '#60a5fa',
  platform_silence_breaking: '#60a5fa',
  viral_spike:               '#f472b6',
  collaboration:             '#a78bfa',
  award:                     '#fbbf24',
  pr_event:                  '#22d3ee',
  tour_announcement:         '#fb923c',
  declining_metrics:         '#f87171',
  platform_silence:          '#f87171',
};

const TICKER_SIGNAL_LABEL: Record<string, string> = {
  rapid_follower_surge:      'SURGE',
  platform_silence_breaking: 'RETURN',
  new_release:               'NEW DROP',
  declining_metrics:         'DECLINE',
  platform_silence:          'DARK',
  viral_spike:               'VIRAL',
  milestone:                 'MILESTONE',
  chart_movement:            'CHART',
  award:                     'AWARD',
  collaboration:             'COLLAB',
  pr_event:                  'PRESS',
  tour_announcement:         'TOUR',
};

function NewsTicker() {
  const items = [...briefing.items, ...briefing.items];
  return (
    <div
      className="anim-fade-in overflow-hidden -mx-6 relative"
      style={{ animationDelay: '180ms' }}
    >
      {/* Top glow line */}
      <div
        className="absolute inset-x-0 top-0 h-[1px]"
        style={{
          background: 'linear-gradient(90deg, transparent, rgba(251,191,36,0.5) 20%, rgba(244,114,182,0.5) 50%, rgba(96,165,250,0.5) 80%, transparent)',
        }}
      />
      {/* Bottom glow line */}
      <div
        className="absolute inset-x-0 bottom-0 h-[1px]"
        style={{
          background: 'linear-gradient(90deg, transparent, rgba(96,165,250,0.5) 20%, rgba(74,222,128,0.5) 50%, rgba(251,191,36,0.5) 80%, transparent)',
        }}
      />

      <div className="bg-[var(--color-bg-secondary)] py-5">
        {/* "BREAKING" label pinned left */}
        <div className="flex items-center">
          <div
            className="flex-shrink-0 flex items-center gap-2 pl-6 pr-4 z-10"
            style={{ background: 'var(--color-bg-secondary)' }}
          >
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-40" style={{ background: '#f87171' }} />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5" style={{ background: '#f87171' }} />
            </span>
            <span
              className="font-[family-name:var(--font-mono)] text-[13px] tracking-[0.3em] uppercase font-bold"
              style={{ color: '#f87171' }}
            >
              Live
            </span>
            <span className="text-[var(--color-border-light)] opacity-40">│</span>
          </div>

          {/* Scrolling items */}
          <div className="overflow-hidden flex-1">
            <div
              className="flex gap-0 whitespace-nowrap items-center"
              style={{ animation: 'ticker 80s linear infinite' }}
            >
              {items.map((item, i) => {
                const accentColor = TICKER_SIGNAL_COLOR[item.signal_type] ?? '#999';
                const signalLabel = TICKER_SIGNAL_LABEL[item.signal_type] ?? item.signal_type.replace(/_/g, ' ').toUpperCase();
                const imgUrl = imageBySlug[item.artist_slug];

                return (
                  <span
                    key={i}
                    className="inline-flex items-center gap-3.5 px-6"
                  >
                    {/* Artist avatar */}
                    {imgUrl && (
                      <img
                        src={imgUrl}
                        alt={item.artist_name}
                        className="w-[44px] h-[44px] rounded-full object-cover flex-shrink-0 border-2"
                        style={{ borderColor: `${accentColor}66` }}
                      />
                    )}

                    {/* Signal badge */}
                    <span
                      className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.15em] uppercase font-bold px-2 py-1 rounded-sm flex-shrink-0"
                      style={{
                        background: `${accentColor}20`,
                        color: accentColor,
                        border: `1px solid ${accentColor}44`,
                      }}
                    >
                      {signalLabel}
                    </span>

                    {/* Artist name */}
                    <span
                      className="font-[family-name:var(--font-mono)] text-[15px] tracking-wider uppercase font-bold flex-shrink-0"
                      style={{ color: accentColor }}
                    >
                      {item.artist_name}
                    </span>

                    {/* Headline */}
                    <span className="text-[var(--color-text-primary)] font-[family-name:var(--font-ui)] text-[16px] font-medium">
                      {item.headline}
                    </span>

                    {/* Separator */}
                    <span
                      className="font-[family-name:var(--font-mono)] text-[14px] opacity-20 ml-3 flex-shrink-0"
                      style={{ color: accentColor }}
                    >
                      ◆
                    </span>
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function NewsFeed() {
  return (
    <section>
      <FadeUp baseDelay={50}>
        <SectionLabel
          label="TOP STORIES"
          meta={`${briefing.items.length} items · ${briefing.news_date}`}
        />
      </FadeUp>
      <div className="flex flex-col gap-2">
        {briefing.items.map((item, i) => (
          <FadeUp key={item.priority} index={i} baseDelay={100}>
            <NewsItem item={item} imageUrl={imageBySlug[item.artist_slug]} />
          </FadeUp>
        ))}
      </div>
    </section>
  );
}

const TIER_OPTIONS = [
  { value: 'all',      label: 'All Tiers',  color: '#9ca3af' },
  { value: 'mega',     label: 'Mega',       color: '#fbbf24' },
  { value: 'major',    label: 'Major',      color: '#60a5fa' },
  { value: 'rising',   label: 'Rising',     color: '#a78bfa' },
  { value: 'emerging', label: 'Emerging',   color: '#34d399' },
] as const;

function RosterGrid() {
  const [tierFilter, setTierFilter] = useState<'all' | 'mega' | 'major' | 'rising' | 'emerging'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const q = searchQuery.trim().toLowerCase();
  const filtered = roster.artists.filter(a => {
    const tierOk = tierFilter === 'all' || snapshotBySlug[a.slug]?.tier === tierFilter;
    if (!tierOk) return false;
    if (!q) return true;
    if (a.name.toLowerCase().includes(q)) return true;
    if (a.aliases?.some(alias => alias.toLowerCase().includes(q))) return true;
    return false;
  });

  const activeTier  = TIER_OPTIONS.find(t => t.value === tierFilter)!;
  // When the search narrows the grid to a single artist, auto-expand the card
  // so the user sees full KPI details without an extra click.
  const autoExpandSingle = q.length > 0 && filtered.length === 1;

  return (
    <section>
      <FadeUp baseDelay={50}>
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4 mb-6">
          <div>
            <h2 className="font-[family-name:var(--font-headline)] font-black text-2xl text-[var(--color-text-primary)] tracking-tight">
              ARTIST ROSTER
            </h2>
            <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] uppercase tracking-widest mt-0.5">
              {filtered.length} of {roster.artist_count} artists
              {q && filtered.length === 1 && ' · expanded below'}
              {!q && ' · click to expand KPIs'}
            </p>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center gap-3 flex-shrink-0">

            {/* Search — left of tier filter */}
            <div className="relative flex items-center">
              <span
                aria-hidden="true"
                className="absolute left-3 font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] pointer-events-none"
              >
                ⌕
              </span>
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search artist…"
                aria-label="Search artists by name"
                className={[
                  'font-[family-name:var(--font-mono)] text-[12px] tracking-wide',
                  'bg-transparent text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)]',
                  'border border-[var(--color-border-light)] rounded-sm',
                  'pl-8 pr-8 py-1.5 w-[240px]',
                  'focus:outline-none focus:border-[var(--color-text-secondary)]',
                  'transition-colors duration-150',
                ].join(' ')}
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  aria-label="Clear search"
                  className="absolute right-2 font-[family-name:var(--font-mono)] text-[14px] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] cursor-pointer leading-none"
                >
                  ×
                </button>
              )}
            </div>

            {/* Tier filter */}
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {TIER_OPTIONS.map(opt => {
                const isActive = tierFilter === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setTierFilter(opt.value)}
                    className="font-[family-name:var(--font-mono)] text-[11px] tracking-widest uppercase px-3 py-1.5 rounded-sm border transition-all duration-150 cursor-pointer"
                    style={{
                      borderColor: isActive ? opt.color : `${opt.color}44`,
                      background:  isActive ? `${opt.color}22` : 'transparent',
                      color:       isActive ? opt.color : `${opt.color}88`,
                    }}
                  >
                    {opt.label}
                    {opt.value !== 'all' && (
                      <span className="ml-1 opacity-60">
                        {roster.artists.filter(a => snapshotBySlug[a.slug]?.tier === opt.value).length}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </FadeUp>

      {filtered.length === 0 ? (
        <p className="font-[family-name:var(--font-mono)] text-[13px] text-[var(--color-text-muted)] py-12 text-center">
          {q
            ? <>No artists match <span className="text-[var(--color-text-primary)]">"{searchQuery}"</span>{tierFilter !== 'all' && <> in the <span style={{ color: activeTier.color }}>{activeTier.label}</span> tier</>}.</>
            : <>No artists in the <span style={{ color: activeTier.color }}>{activeTier.label}</span> tier.</>}
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {filtered.map((artist, i) => {
            const snap = snapshotBySlug[artist.slug];
            if (!snap) return null;
            return (
              <FadeUp key={artist.slug} index={i} baseDelay={100}>
                <ArtistCard
                  artist={artist}
                  snapshot={snap}
                  initiallyExpanded={autoExpandSingle}
                />
              </FadeUp>
            );
          })}
        </div>
      )}
    </section>
  );
}

function Leaderboards() {
  return (
    <section>
      <FadeUp baseDelay={50}>
        <SectionLabel
          label="KPI LEADERBOARDS"
          meta="top 5 per metric · click ↓↑ to sort"
        />
      </FadeUp>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] as const).map((id, i) => (
          <FadeUp key={id} index={i} baseDelay={100}>
            <KpiLeaderboard kpiId={id} artists={snapshot.artists} />
          </FadeUp>
        ))}
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-[var(--color-border)] pt-8 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-6">
        <div className="space-y-1">
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.2em] text-[var(--color-text-muted)] uppercase">
            Last Refreshed
          </p>
          <p className="font-[family-name:var(--font-mono)] text-[13px] text-[var(--color-text-secondary)]">
            {snapshot.snapshot_date} · prev {snapshot.previous_snapshot_date}
          </p>
        </div>

        <div className="space-y-1 sm:text-center">
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.2em] text-[var(--color-text-muted)] uppercase">
            Data Sources
          </p>
          <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)]">
            Social aggregators · Spotify (direct) · YouTube · Press search
          </p>
        </div>

        <div className="space-y-1 sm:text-right">
          <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.2em] text-[var(--color-text-muted)] uppercase">
            Version
          </p>
          <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)]">
            Sony Latin Pulse v0.1 · {roster.artist_count} artists · 11 KPIs
          </p>
        </div>
      </div>

      <div className="border-t border-[var(--color-border)] mt-8 pt-4 flex flex-col sm:flex-row items-center justify-between gap-3">
        <span className="font-[family-name:var(--font-headline)] font-black text-[13px] text-[var(--color-text-muted)] tracking-widest">
          SONY LATIN PULSE
        </span>
        <span className="font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-text-muted)] opacity-40">
          © Sony Music Entertainment
        </span>
      </div>

      {/* Chromdata attribution */}
      <div className="mt-5 pt-4 border-t border-[var(--color-border)] flex flex-col sm:flex-row items-center justify-center gap-2 text-center">
        <span className="font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-text-muted)] opacity-50 tracking-widest uppercase">
          Powered by
        </span>
        <span className="font-[family-name:var(--font-headline)] font-black text-[14px] tracking-wide"
          style={{ color: '#60a5fa' }}>
          CHROMADATA
        </span>
        <span className="font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-text-muted)] opacity-50 tracking-widest uppercase">
          · Artist Intelligence Solutions
        </span>
      </div>
    </footer>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [activeTab,        setActiveTab]        = useState<Tab>('stories');
  const [selectedQuestion, setSelectedQuestion] = useState('');
  const { theme, toggle: toggleTheme } = useTheme();

  function handleQuestionNavigate(question: string) {
    setSelectedQuestion(question);
    setActiveTab('analyst');
  }

  return (
    <div className="min-h-screen bg-[var(--color-bg-primary)]">

      <div className="px-6 pt-10">
        <Masthead theme={theme} onToggleTheme={toggleTheme} />
      </div>

      {/* Full-bleed ticker — always visible on every tab */}
      <div className="mt-6">
        <NewsTicker />
      </div>

      <div className="px-6 mt-8">
        <TabNav active={activeTab} onSelect={setActiveTab} />

        {activeTab === 'overview'     && <Overview />}
        {activeTab === 'stories'      && <NewsFeed />}
        {activeTab === 'roster'       && <RosterGrid />}
        {activeTab === 'leaderboards' && <Leaderboards />}
        {activeTab === 'analyst'      && (
          <>
            <ChatAgent
              roster={roster}
              snapshot={snapshot}
              briefing={briefing}
              onQuestionNavigate={handleQuestionNavigate}
            />
            <AnalystPage
              question={selectedQuestion}
              systemPrompt={systemPrompt}
              snapshotDate={snapshot.snapshot_date}
              apiKey={apiKey}
              onSelectQuestion={handleQuestionNavigate}
            />
          </>
        )}

        <Divider />
        <Footer />
      </div>
    </div>
  );
}
