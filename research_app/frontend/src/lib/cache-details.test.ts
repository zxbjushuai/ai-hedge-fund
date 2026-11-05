import { expect, it, vi } from 'vitest';
import { createDetailLoader } from './cache-details';
import type { CachedSecurityDetail } from '../services/simulation-api';

it('deduplicates and caps concurrent details at four across selections', async () => {
  let active = 0, peak = 0;
  const fetcher = vi.fn(async (ticker: string) => { active++; peak = Math.max(peak, active); await new Promise(resolve => setTimeout(resolve, 2)); active--; return { ticker } as CachedSecurityDetail; });
  const loader = createDetailLoader(fetcher);
  const first = loader.get('A'); expect(loader.get('A')).toBe(first);
  await Promise.all([first, ...Array.from({ length: 12 }, (_, i) => loader.get(String(i)))]);
  expect(peak).toBe(4); expect(fetcher).toHaveBeenCalledTimes(13);
  loader.invalidate(); await loader.get('A'); expect(fetcher).toHaveBeenCalledTimes(14);
});

it('retries failures and does not reuse stale generation responses', async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ ticker: 'A' });
  const loader = createDetailLoader(fetcher);
  await expect(loader.get('A')).rejects.toThrow('offline');
  await expect(loader.get('A')).resolves.toEqual({ ticker: 'A' });
  loader.invalidate(); await loader.get('A'); expect(fetcher).toHaveBeenCalledTimes(3);
});

it('rejects obsolete queued requests and keeps new-generation results isolated', async () => {
  let release!: (value: CachedSecurityDetail) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise(resolve => { release = resolve; })).mockResolvedValue({ ticker: 'new' });
  const loader = createDetailLoader(fetcher, 1);
  const first = loader.get('A');
  const queued = loader.get('B');
  const rejected = expect(queued).rejects.toThrow('Cache changed');
  await Promise.resolve();
  loader.invalidate();
  const next = loader.get('A');
  release({ ticker: 'old' } as CachedSecurityDetail);
  await first; await rejected;
  await expect(next).resolves.toEqual({ ticker: 'new' });
  expect(loader.get('A')).toBe(next); expect(fetcher).toHaveBeenCalledTimes(2);
});
