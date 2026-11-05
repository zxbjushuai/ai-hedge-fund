import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LlmProvidersSettings } from './llm-providers';
import { llmProvidersApi, type LlmProviderConnection, type LlmProtocol } from '@/services/llm-providers-api';

function connection(id: number, vendor: LlmProviderConnection['vendor'], protocol: LlmProtocol): LlmProviderConnection {
  return { id, name: vendor === 'opencode_go' ? 'Legacy direct Go' : 'Relay', vendor, protocol,
    provider_type: vendor, base_url: 'http://127.0.0.1:18081/v1', enabled: true,
    has_api_key: true, api_key_masked: '****demo', last_tested_at: null,
    last_test_status: null, last_error: null, last_synced_at: null };
}

beforeEach(() => {
  vi.spyOn(llmProvidersApi, 'list').mockResolvedValue({ providers: [] });
  vi.spyOn(llmProvidersApi, 'listModels').mockResolvedValue({ models: [] });
});
afterEach(cleanup);

it.each<LlmProtocol>(['openai_chat_completions', 'openai_responses', 'anthropic_messages'])(
  'creates a generic %s relay without exposing a vendor mode', async protocol => {
    const create = vi.spyOn(llmProvidersApi, 'create').mockResolvedValue(connection(1, 'custom', protocol));
    render(<LlmProvidersSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'Add Provider' }));
    expect(screen.queryByText('Vendor')).toBeNull();
    expect(screen.getAllByRole('option').map(item => item.textContent)).toEqual([
      'OpenAI Chat Completions', 'OpenAI Responses', 'Anthropic Messages',
    ]);
    fireEvent.change(screen.getByLabelText('Base URL'), { target: { value: 'http://127.0.0.1:18081/v1' } });
    fireEvent.change(screen.getByLabelText('Protocol'), { target: { value: protocol } });
    expect((screen.getByLabelText('Base URL') as HTMLInputElement).value).toBe('http://127.0.0.1:18081/v1');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Relay' } });
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'test-only-downstream-key' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: 'Relay', vendor: 'custom', protocol,
      base_url: 'http://127.0.0.1:18081/v1', api_key: 'test-only-downstream-key', enabled: true }));
    await screen.findByText('Connection saved.');
  },
);

it('hides stored Go connections and preserves an existing connection vendor and key on edit', async () => {
  const existing = connection(2, 'openai', 'openai_responses');
  vi.mocked(llmProvidersApi.list).mockResolvedValue({ providers: [connection(1, 'opencode_go', 'openai_chat_completions'), existing] });
  const update = vi.spyOn(llmProvidersApi, 'update').mockResolvedValue(existing);
  render(<LlmProvidersSettings />);
  await screen.findByDisplayValue('Relay');
  expect(screen.queryByText('Legacy direct Go')).toBeNull();
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed relay' } });
  fireEvent.click(screen.getByRole('button', { name: /^Save$/ }));
  await waitFor(() => expect(update).toHaveBeenCalledWith(2, {
    name: 'Renamed relay', base_url: existing.base_url, enabled: true,
  }));
  await screen.findByText('Connection saved.');
});
