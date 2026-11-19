import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { RuntimeStatusPanel } from './runtime-status';
import { simulationApi, type SystemStatus } from '@/services/simulation-api';

const status: SystemStatus = {
  startup_recovery: {
    completed_at: '2026-11-19T01:03:58+00:00',
    orphaned_simulations_recovered: 2,
    orphaned_simulations_failed: 2,
    orphaned_simulations_cancelled: 0,
    simulation_ids: [4, 7],
    orphaned_cache_jobs_failed: 1,
    cache_job_ids: ['cache-3'],
  },
  simulations: {
    pending: 1,
    running: 1,
    cancelling: 0,
    completed: 5,
    failed: 3,
    cancelled: 1,
  },
  cache_jobs: {
    total: 4,
    active: 1,
    by_status: {
      pending: 0,
      running: 1,
      cancelling: 0,
      completed: 2,
      partial: 1,
      failed: 0,
      cancelled: 0,
    },
  },
};

beforeEach(() => {
  vi.spyOn(simulationApi, 'getSystemStatus').mockResolvedValue(status);
});
afterEach(cleanup);

it('shows loading and then startup, simulation, and cache-job counts', async () => {
  let resolve!: (value: SystemStatus) => void;
  vi.mocked(simulationApi.getSystemStatus).mockImplementation(() => new Promise(done => { resolve = done; }));

  render(<RuntimeStatusPanel active refreshKey={0} />);
  expect(screen.getByRole('status').textContent).toContain('Loading runtime status');

  resolve(status);
  await screen.findByText('2 simulations recovered');
  expect(screen.queryByText('2 failed · 0 cancelled · 1 cache job failed')).not.toBeNull();
  expect(screen.queryByText('2 active · 3 failed')).not.toBeNull();
  expect(screen.queryByText('1 pending · 1 running · 0 cancelling')).not.toBeNull();
  expect(screen.queryByText('1 active', { selector: 'dd' })).not.toBeNull();
  expect(screen.queryByText('4 tracked this process')).not.toBeNull();
  expect(screen.queryByText(/Last startup check/)).not.toBeNull();
});

it('keeps a successful snapshot while reporting a failed refresh and retries', async () => {
  render(<RuntimeStatusPanel active refreshKey={0} />);
  await screen.findByText('2 simulations recovered');

  vi.mocked(simulationApi.getSystemStatus).mockRejectedValueOnce(new Error('status offline'));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh runtime status' }));
  await screen.findByText(/Runtime status unavailable: status offline/);
  expect(screen.queryByText('2 simulations recovered')).not.toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Retry runtime status' }));
  await waitFor(() => expect(screen.queryByText(/Runtime status unavailable/)).toBeNull());
  expect(simulationApi.getSystemStatus).toHaveBeenCalledTimes(3);
});

it('does not request status while the Simulation page is inactive', () => {
  render(<RuntimeStatusPanel active={false} refreshKey={0} />);
  expect(screen.queryByRole('region', { name: 'Runtime status' })).toBeNull();
  expect(simulationApi.getSystemStatus).not.toHaveBeenCalled();
});
