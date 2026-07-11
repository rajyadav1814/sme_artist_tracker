/**
 * Data loader — resolves the three data sources the frontend needs.
 *
 * roster:   data/roster.json          (single current file)
 * snapshot: latest data/snapshots/*-kpis.json  (newest YYYY-MM-DD-kpis.json)
 * briefing: latest data/news/YYYY-MM-DD.json   (newest dated briefing)
 *
 * import.meta.glob bundles every matching file at build time.  Sorting module
 * keys alphabetically and taking the last entry picks the most recent date.
 * Old snapshot files accumulate slowly (one per day); prune data/snapshots/ to
 * the last 7–14 days if bundle size becomes a concern.
 */

import type { Roster, Snapshot, NewsBriefing } from './types';

// ── Roster ────────────────────────────────────────────────────────────────────

import rosterJson from '../../data/roster.json';

export const roster: Roster = rosterJson as unknown as Roster;

// ── KPI snapshots ─────────────────────────────────────────────────────────────

const kpiModules = import.meta.glob<{ default: unknown }>(
  '../../data/snapshots/*-kpis.json',
  { eager: true },
);

// ── News briefings ────────────────────────────────────────────────────────────

// Pattern matches YYYY-MM-DD.json only; excludes the fixed-alias news.json at
// the data/ root so we always get a dated briefing file.
const newsModules = import.meta.glob<{ default: unknown }>(
  '../../data/news/????-??-??.json',
  { eager: true },
);

// ── Resolver ──────────────────────────────────────────────────────────────────

function latest<T>(modules: Record<string, { default: unknown }>): T | null {
  const keys = Object.keys(modules).sort();   // ascending — last key = newest date
  return keys.length ? (modules[keys[keys.length - 1]].default as T) : null;
}

// ── Exports ───────────────────────────────────────────────────────────────────

export const snapshot: Snapshot = latest<Snapshot>(kpiModules) ?? {
  snapshot_date:          '—',
  previous_snapshot_date: '—',
  artists:                [],
};

export const briefing: NewsBriefing = latest<NewsBriefing>(newsModules) ?? {
  news_date:       '—',
  source_snapshot: '—',
  items:           [],
};
