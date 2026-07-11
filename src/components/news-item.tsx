import type { NewsItem as NewsItemType, NewsKpiImpact } from '../data/types';

// ─── Formatters ──────────────────────────────────────────────────────────────

function fmtNumber(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

function fmtTimestamp(iso: string): string {
  const d   = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffH  = Math.round(diffMs / 3_600_000);
  if (diffH < 1)  return 'just now';
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.round(diffH / 24)}d ago`;
}

const SIGNAL_LABEL: Record<string, string> = {
  rapid_follower_surge:      'RAPID SURGE',
  platform_silence_breaking: 'SILENCE → ACTIVE',
  new_release:               'NEW RELEASE',
  declining_metrics:         'DECLINING',
  platform_silence:          'GOING DARK',
  viral_spike:               'VIRAL',
  milestone:                 'MILESTONE',
  chart_movement:            'CHART MOVE',
  award:                     'AWARD',
  collaboration:             'COLLAB',
  pr_event:                  'PR EVENT',
  tour_announcement:         'TOUR',
};

// Background + text colour pairs per signal type — each category has a distinct
// hue so the badge reads immediately at a glance across the stories list.
interface BadgeStyle { bg: string; text: string; border: string }

const SIGNAL_STYLE: Record<string, BadgeStyle> = {
  milestone:                 { bg: '#fbbf2422', text: '#fbbf24', border: '#fbbf2466' }, // amber  — achievement
  new_release:               { bg: '#4ade8022', text: '#4ade80', border: '#4ade8066' }, // green  — launch
  chart_movement:            { bg: '#4ade8022', text: '#4ade80', border: '#4ade8066' }, // green  — chart win
  rapid_follower_surge:      { bg: '#60a5fa22', text: '#60a5fa', border: '#60a5fa66' }, // blue   — growth
  platform_silence_breaking: { bg: '#60a5fa22', text: '#60a5fa', border: '#60a5fa66' }, // blue   — return
  viral_spike:               { bg: '#f472b622', text: '#f472b6', border: '#f472b666' }, // pink   — viral
  collaboration:             { bg: '#a78bfa22', text: '#a78bfa', border: '#a78bfa66' }, // violet — collab
  award:                     { bg: '#fbbf2422', text: '#fbbf24', border: '#fbbf2466' }, // amber  — accolade
  pr_event:                  { bg: '#22d3ee22', text: '#22d3ee', border: '#22d3ee66' }, // cyan   — press
  tour_announcement:         { bg: '#fb923c22', text: '#fb923c', border: '#fb923c66' }, // orange — tour
  declining_metrics:         { bg: '#f8717122', text: '#f87171', border: '#f8717166' }, // red    — decline
  platform_silence:          { bg: '#f8717122', text: '#f87171', border: '#f8717166' }, // red    — going dark
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function TrendArrow({ dir }: { dir: string }) {
  if (dir === 'up')   return <span className="text-[var(--color-accent-up)]">▲</span>;
  if (dir === 'down') return <span className="text-[var(--color-accent-down)]">▼</span>;
  return <span className="text-[var(--color-text-muted)]">—</span>;
}

function KpiImpactBadge({ impact }: { impact: NewsKpiImpact }) {
  const dir      = impact.direction ?? 'flat';
  const absVal   = impact.delta_absolute ?? null;
  const pctVal   = impact.delta_percent  ?? null;
  const hasDelta = absVal != null || pctVal != null;

  return (
    <span className="inline-flex items-center gap-1 font-[family-name:var(--font-mono)] text-[14px]">
      <span className="text-[var(--color-text-muted)]">{impact.kpi_name}</span>
      {hasDelta && (
        <span className={
          dir === 'up'   ? 'text-[var(--color-accent-up)]' :
          dir === 'down' ? 'text-[var(--color-accent-down)]' :
          'text-[var(--color-text-muted)]'
        }>
          <TrendArrow dir={dir} />
          {absVal != null && (
            <span> {absVal > 0 ? '+' : ''}{fmtNumber(absVal)}</span>
          )}
          {pctVal != null && Math.abs(pctVal) < 500 && (
            <span className="opacity-60"> ({pctVal > 0 ? '+' : ''}{pctVal.toFixed(1)}%)</span>
          )}
        </span>
      )}
      {!hasDelta && impact.current_value != null && (
        <span className="text-[var(--color-text-secondary)]">
          {fmtNumber(impact.current_value)}
          {impact.benchmark_tier && (
            <span className="opacity-60"> · {impact.benchmark_tier}</span>
          )}
        </span>
      )}
    </span>
  );
}

function ConfidenceDots({ dots }: { dots: string }) {
  const filled   = (dots.match(/●/g) ?? []).length;
  const unfilled = (dots.match(/○/g) ?? []).length;
  return (
    <span className="font-[family-name:var(--font-mono)] text-[13px] tracking-widest" title={`Data confidence: ${filled}/${filled + unfilled}`}>
      <span className="text-[var(--color-text-secondary)]">{'●'.repeat(filled)}</span>
      <span className="text-[var(--color-border-light)] opacity-50">{'○'.repeat(unfilled)}</span>
    </span>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export interface NewsItemProps {
  item:      NewsItemType;
  imageUrl?: string;
}

export function NewsItem({ item, imageUrl }: NewsItemProps) {
  const signalLabel   = SIGNAL_LABEL[item.signal_type] ?? item.signal_type.replace(/_/g, ' ').toUpperCase();
  const isTop3        = item.priority <= 3;
  const primaryImpact = item.kpi_impact[0] ?? null;

  const fallbackSrc = `https://placehold.co/48x48/1A1A1A/444444?text=${encodeURIComponent(item.artist_slug)}`;

  return (
    <article className={[
      'group relative flex gap-4 items-start overflow-hidden',
      'bg-[var(--color-bg-card)] border border-[var(--color-border)]',
      'border-l-2 border-l-transparent',
      'rounded-sm px-4 py-4',
      'transition-all duration-300 ease-out',
      'hover:bg-[var(--color-bg-card-hover)] hover:border-[var(--color-border-light)]',
      'hover:border-l-[var(--color-text-muted)]',
      isTop3 ? 'hover:border-l-[var(--color-text-primary)]' : '',
    ].join(' ')}>

      {/* ── Priority badge ──────────────────────────────────────────── */}
      <div className="flex-shrink-0 w-8 text-right">
        <span className={[
          'font-[family-name:var(--font-headline)] font-black leading-none',
          isTop3
            ? 'text-[24px] text-[var(--color-text-primary)]'
            : 'text-[20px] text-[var(--color-text-muted)]',
        ].join(' ')}>
          {item.priority}
        </span>
      </div>

      {/* ── Artist thumbnail — 1.5 inches / 144px ─────────────────── */}
      <div className="flex-shrink-0">
        <img
          src={imageUrl ?? fallbackSrc}
          alt={item.artist_name}
          width={144}
          height={144}
          className={[
            'w-[144px] h-[144px] rounded-full object-cover',
            'border-2 border-[var(--color-border-light)]',
            'grayscale transition-all duration-500 ease-out',
            'group-hover:grayscale-0 group-hover:border-white/20',
            'group-hover:shadow-[0_0_24px_rgba(255,255,255,0.08)]',
          ].join(' ')}
          onError={e => { e.currentTarget.src = fallbackSrc; }}
        />
      </div>

      {/* ── Content ─────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0">

        {/* Signal type + artist name row */}
        <div className="flex flex-wrap items-center gap-2 mb-1.5">
          {/* Colour-coded signal badge */}
          {(() => {
            const style = SIGNAL_STYLE[item.signal_type] ?? { bg: '#ffffff18', text: '#ffffff', border: '#ffffff44' };
            return (
              <span
                className="font-[family-name:var(--font-mono)] text-[13px] tracking-widest uppercase px-2 py-0.5 rounded-sm font-bold"
                style={{ background: style.bg, color: style.text, border: `1px solid ${style.border}` }}
              >
                {signalLabel}
              </span>
            );
          })()}
          <span className="font-[family-name:var(--font-mono)] text-[14px] text-[var(--color-text-muted)] uppercase tracking-widest">
            {item.artist_name}
            <span className="ml-1.5 opacity-40">·</span>
            <span className="ml-1.5">{item.artist_tier.toUpperCase()}</span>
          </span>
        </div>

        {/* Headline */}
        <h3 className={[
          'font-[family-name:var(--font-headline)] font-black leading-tight text-[var(--color-text-primary)]',
          isTop3 ? 'text-[19px]' : 'text-[17px]',
        ].join(' ')}>
          {item.headline}
        </h3>

        {/* KPI impact line */}
        {primaryImpact && (
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {item.kpi_impact.slice(0, 3).map(impact => (
              <KpiImpactBadge key={impact.kpi_id} impact={impact} />
            ))}
          </div>
        )}

        {/* Summary blurb */}
        <p className="mt-2 text-[15px] text-[var(--color-text-secondary)] leading-relaxed line-clamp-3">
          {item.summary}
        </p>

        {/* Footer: timestamp · source · confidence */}
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="font-[family-name:var(--font-mono)] text-[13px] text-[var(--color-text-muted)]">
            {fmtTimestamp(item.timestamp)}
          </span>
          <span className="text-[var(--color-border-light)] opacity-40 text-[13px]">·</span>
          <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)] truncate max-w-[240px]" title={item.source}>
            {item.source.split(';')[0].trim()}
          </span>
          <span className="text-[var(--color-border-light)] opacity-40 text-[13px]">·</span>
          <ConfidenceDots dots={item.data_confidence} />
        </div>
      </div>
    </article>
  );
}
