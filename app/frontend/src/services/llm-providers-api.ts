const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

export interface LlmProviderConnection {
  id: number;
  name: string;
  provider_type: string;
  vendor: LlmVendor;
  protocol: LlmProtocol;
  base_url: string;
  enabled: boolean;
  has_api_key: boolean;
  api_key_masked: string;
  last_tested_at: string | null;
  last_test_status: 'success' | 'failed' | null;
  last_error: string | null;
  last_synced_at: string | null;
}

export type LlmVendor = 'openai' | 'anthropic' | 'opencode_go' | 'modelscope' | 'custom';
export type LlmProtocol = 'openai_chat_completions' | 'openai_responses' | 'anthropic_messages';

export interface LlmProviderModel {
  id: number;
  connection_id: number;
  model_id: string;
  display_name: string;
  source: 'remote' | 'manual';
  enabled: boolean;
  available: boolean;
  last_seen_at: string | null;
}

export interface LlmProviderInput {
  name: string;
  vendor: LlmVendor;
  protocol: LlmProtocol;
  base_url: string;
  api_key: string;
  enabled: boolean;
}

export const llmProvidersApi = {
  list: () => jsonRequest<{ providers: LlmProviderConnection[] }>('/dashboard/llm/providers'),
  create: (data: LlmProviderInput) => jsonRequest<LlmProviderConnection>('/dashboard/llm/providers', {
    method: 'POST', body: JSON.stringify(data),
  }),
  update: (id: number, data: Partial<Omit<LlmProviderInput, 'vendor' | 'protocol'>>) =>
    jsonRequest<LlmProviderConnection>(`/dashboard/llm/providers/${id}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),
  test: (id: number) => jsonRequest<{ status: string; model_count: number }>(
    `/dashboard/llm/providers/${id}/test`, { method: 'POST' },
  ),
  syncModels: (id: number) => jsonRequest<{ models: LlmProviderModel[] }>(
    `/dashboard/llm/providers/${id}/models/sync`, { method: 'POST' },
  ),
  listModels: (id: number) => jsonRequest<{ models: LlmProviderModel[] }>(
    `/dashboard/llm/providers/${id}/models`,
  ),
  addModel: (id: number, model_id: string, display_name?: string) =>
    jsonRequest<LlmProviderModel>(`/dashboard/llm/providers/${id}/models`, {
      method: 'POST', body: JSON.stringify({ model_id, display_name: display_name || undefined, enabled: true }),
    }),
  updateModel: (connectionId: number, modelId: string, data: { enabled?: boolean; display_name?: string }) =>
    jsonRequest<LlmProviderModel>(
      `/dashboard/llm/providers/${connectionId}/models/${encodeURIComponent(modelId)}`,
      { method: 'PATCH', body: JSON.stringify(data) },
    ),
};
