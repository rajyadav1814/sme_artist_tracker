/**
 * Data loader — resolves the three data sources the frontend needs.
 *
 * roster:   data/roster.json
 * snapshot: data/snapshot.json
 * briefing: data/news.json
 */

import type { Roster, Snapshot, NewsBriefing } from './types';

import rosterJson from '../../data/roster.json';
import snapshotJson from '../../data/snapshot.json';
import newsJson from '../../data/news.json';

export const roster: Roster = rosterJson as unknown as Roster;
export const snapshot: Snapshot = snapshotJson as unknown as Snapshot;
export const briefing: NewsBriefing = newsJson as unknown as NewsBriefing;

