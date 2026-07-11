/**
 * Shared AI utilities — system prompt builder + streaming fetch.
 * Used by both ChatAgent (inline chat) and AnalystPage (full-page answer).
 */

import type { Roster, Snapshot, NewsBriefing } from '../data/types';

// ── Suggested questions (single source of truth) ──────────────────────────────

export const SUGGESTED_QUESTIONS: { text: string; color: string }[] = [
  { text: 'Who has the highest total social reach on the roster today?',             color: '#60a5fa' }, // blue
  { text: 'Which artists are growing fastest right now — and by how much?',          color: '#4ade80' }, // green
  { text: 'Who leads in Spotify monthly listeners, and who is trending up the most?',color: '#fbbf24' }, // amber
  { text: 'Are any artists going silent on social media? Should we be concerned?',   color: '#f472b6' }, // pink
  { text: "What's the most important story in today's briefing and why?",            color: '#a78bfa' }, // violet
  { text: 'Which artists released new music in the past 2 weeks?',                   color: '#22d3ee' }, // cyan
  { text: 'Who has the best engagement rate — and what does that signal about their fanbase?', color: '#fb923c' }, // orange
  { text: 'Which emerging or rising-tier artists have the strongest momentum right now?',       color: '#34d399' }, // emerald
  { text: 'If you had to flag 3 artists for an urgent A&R conversation, who and why?',          color: '#e879f9' }, // fuchsia
  { text: 'Which artists have multiple active KPI alerts — give me the full picture.',           color: '#f87171' }, // red
];

// ── Number formatter ─────────────────────────────────────────────────────────

function fmtN(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

// ── System prompt builder ─────────────────────────────────────────────────────

export function buildSystemPrompt(
  roster:   Roster,
  snapshot: Snapshot,
  briefing: NewsBriefing,
): string {
  const artistLines = snapshot.artists.map(a => {
    const kpi = Object.fromEntries(a.kpis.map(k => [k.kpi_id, k]));
    const alerts      = a.kpis.filter(k => k.alert).map(k => k.alert).join(', ');
    const reach       = kpi[1];
    const velocity    = kpi[2];
    const eng         = kpi[3];
    const spotify     = kpi[4];
    const spotifyTrend = kpi[5];
    const content     = kpi[6];
    const diversity   = kpi[7];
    const video       = kpi[8];
    const recency     = kpi[9];
    const press       = kpi[10];

    return [
      `${a.artist_name} [${a.tier.toUpperCase()}]`,
      `  Social Reach: ${fmtN(reach?.current_value)} (velocity ${velocity?.current_value?.toFixed(1) ?? '—'}% ${velocity?.trend ?? ''})`,
      `  Engagement Rate: ${eng?.current_value?.toFixed(2) ?? '—'}% [${eng?.benchmark_tier ?? '—'}]`,
      `  Spotify Listeners: ${fmtN(spotify?.current_value)} (trend ${spotifyTrend?.current_value?.toFixed(1) ?? '—'}%)`,
      `  Content Velocity: ${content?.current_value ?? '—'} posts/week`,
      `  Platform Diversity: ${diversity?.current_value != null ? (diversity.current_value * 100).toFixed(0) : '—'}%`,
      `  Video View Momentum: ${fmtN(video?.current_value)}`,
      `  Release Recency: ${recency?.current_value ?? '—'} days ago [${recency?.benchmark_tier ?? '—'}]`,
      `  Press Mentions: ${press?.current_value ?? '—'} articles/week`,
      alerts ? `  ALERTS: ${alerts}` : `  Alerts: none`,
    ].join('\n');
  });

  const newsLines = briefing.items.map(item =>
    `  #${item.priority} ${item.artist_name} [${item.signal_type}] — ${item.headline}\n  → ${item.summary}`,
  );

  const megaArtists   = snapshot.artists.filter(a => a.tier === 'mega').map(a => a.artist_name);
  const majorArtists  = snapshot.artists.filter(a => a.tier === 'major').map(a => a.artist_name);
  const risingArtists = snapshot.artists.filter(a => a.tier === 'rising').map(a => a.artist_name);

  return `You are an embedded AI analyst inside the Sony Music Latin Artist Intelligence Dashboard.
You have access to today's live KPI snapshot for all ${roster.artist_count} artists on the roster.

Snapshot date: ${snapshot.snapshot_date}
Previous snapshot: ${snapshot.previous_snapshot_date}
Total artists: ${roster.artist_count}
Total active alerts: ${snapshot.artists.reduce((n, a) => n + a.kpis.filter(k => k.alert).length, 0)}

ARTIST TIERS:
  Mega (>50M total reach): ${megaArtists.join(', ')}
  Major (10M–50M): ${majorArtists.join(', ')}
  Rising (1M–10M): ${risingArtists.join(', ')}
  Emerging (<1M): remaining artists

═══════════════════════════════════════════
FULL KPI DATA — ALL ARTISTS
═══════════════════════════════════════════
${artistLines.join('\n\n')}

═══════════════════════════════════════════
TODAY'S NEWS BRIEFING (${briefing.news_date})
═══════════════════════════════════════════
${newsLines.join('\n\n')}

INSTRUCTIONS:
- Answer using the real data above — always cite specific numbers.
- Be thorough and detailed. Lead with the most interesting finding.
- When comparing artists, always include tier context.
- Structure answers clearly: use bullet points, numbered lists, or short paragraphs.
- Bold key names and numbers in your answer using **bold** markdown.
- If data is missing (—), acknowledge it rather than guessing.
- You are speaking to Sony Music Latin A&R / marketing staff — use industry language.
- For the dedicated answer page, write a comprehensive answer (300–500 words minimum).`;
}

// ── Streaming API call ────────────────────────────────────────────────────────

export interface Message {
  role:    'user' | 'assistant';
  content: string;
}

export async function streamAnswer(
  apiKey:       string,
  systemPrompt: string,
  messages:     Message[],
  onChunk:      (text: string) => void,
  onDone:       () => void,
  onError:      (msg: string) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch('https://api.anthropic.com/v1/messages', {
      method:  'POST',
      headers: {
        'x-api-key':                                 apiKey,
        'anthropic-version':                         '2023-06-01',
        'content-type':                              'application/json',
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model:      'claude-sonnet-4-6',
        max_tokens: 2048,
        stream:     true,
        system:     systemPrompt,
        messages:   messages.map(m => ({ role: m.role, content: m.content })),
      }),
    });
  } catch {
    onError('Network error — check your connection.');
    return;
  }

  if (!response.ok) {
    const errText = await response.text().catch(() => response.statusText);
    onError(`API error ${response.status}: ${errText.slice(0, 120)}`);
    return;
  }

  const reader  = response.body?.getReader();
  const decoder = new TextDecoder();
  if (!reader) { onError('No response stream.'); return; }

  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (!raw || raw === '[DONE]') continue;
      try {
        const parsed = JSON.parse(raw);
        if (parsed.type === 'content_block_delta' && parsed.delta?.type === 'text_delta') {
          onChunk(parsed.delta.text as string);
        }
      } catch { /* ignore malformed SSE lines */ }
    }
  }
  onDone();
}
