import { simulationApi, type CachedSecurityDetail } from '../services/simulation-api';

// A shared queue, not one queue per selection: rapid selection changes cannot
// multiply the four-request concurrency limit. Old generations never populate it.
export function createDetailLoader(fetchDetail: (ticker: string) => Promise<CachedSecurityDetail>, limit = 4) {
  let generation = 0;
  let active = 0;
  const queue: Array<() => void> = [];
  const cache = new Map<string, Promise<CachedSecurityDetail>>();
  function pump() {
    while (active < limit && queue.length) queue.shift()!();
  }
  return {
    invalidate() { generation++; cache.clear(); },
    get(ticker: string) {
      const existing = cache.get(ticker);
      if (existing) return existing;
      const requestedGeneration = generation;
      const pending = new Promise<CachedSecurityDetail>((resolve, reject) => {
        queue.push(() => {
          if (requestedGeneration !== generation) { reject(new Error('Cache changed; refresh coverage.')); return; }
          active++;
          Promise.resolve().then(() => fetchDetail(ticker)).then(resolve, reject).finally(() => { active--; pump(); });
        });
        pump();
      });
      cache.set(ticker, pending);
      pending.catch(() => { if (cache.get(ticker) === pending) cache.delete(ticker); });
      return pending;
    },
  };
}
export const cacheDetails = createDetailLoader(ticker => simulationApi.getCachedSecurity(ticker));
