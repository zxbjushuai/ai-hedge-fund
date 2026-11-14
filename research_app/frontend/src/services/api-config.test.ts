import { describe, expect, it } from 'vitest';

import { isLoopbackHostname, resolveApiBaseUrl } from './api-config';

describe('api config', () => {
  it('keeps the configured API URL for localhost development', () => {
    expect(resolveApiBaseUrl({ hostname: 'localhost', origin: 'http://localhost:5173' }, 'http://localhost:8000'))
      .toBe('http://localhost:8000');
    expect(resolveApiBaseUrl({ hostname: '127.0.0.1', origin: 'http://127.0.0.1:5173' }, ''))
      .toBe('http://localhost:8000');
  });

  it('uses the same tailnet origin for remote pages', () => {
    expect(resolveApiBaseUrl(
      { hostname: 'aihf-node.tailnet.ts.net', origin: 'https://aihf-node.tailnet.ts.net' },
      'http://localhost:8000',
    )).toBe('https://aihf-node.tailnet.ts.net');
  });

  it('recognizes loopback host spellings', () => {
    expect(isLoopbackHostname('127.0.0.2')).toBe(true);
    expect(isLoopbackHostname('::1')).toBe(true);
    expect(isLoopbackHostname('127.0.0.1.attacker.example')).toBe(false);
    expect(isLoopbackHostname('100.84.98.125')).toBe(false);
  });
});
