/**
 * Honest social proof. We only ever show numbers the BACKEND actually returns.
 * If the endpoint is missing or fails, we return null and the UI shows a
 * generic trust line with NO numbers — never fabricated counts.
 *
 * Suggested backend: GET /api/stats → { members, signals_24h, upgrades_7d }
 */
import { api } from '@/lib/api';

export interface SocialStats {
  members?: number;
  signals_24h?: number;
  upgrades_7d?: number;
}

export async function getSocialStats(): Promise<SocialStats | null> {
  try {
    const s = await api.get<SocialStats>('/stats');
    // Guard against an endpoint that exists but returns junk.
    if (s && typeof s === 'object') return s;
    return null;
  } catch {
    return null;
  }
}
