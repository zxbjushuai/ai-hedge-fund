import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  llmProvidersApi,
  type LlmProviderConnection,
  type LlmProviderModel,
} from '@/services/llm-providers-api';
import { CheckCircle2, Plus, RefreshCw, Server, XCircle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

const defaults = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
};

const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error);

export function LlmProvidersSettings() {
  const [providers, setProviders] = useState<LlmProviderConnection[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [models, setModels] = useState<LlmProviderModel[]>([]);
  const [name, setName] = useState('');
  const [providerType, setProviderType] = useState<'openai' | 'anthropic'>('openai');
  const [baseUrl, setBaseUrl] = useState(defaults.openai);
  const [apiKey, setApiKey] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [manualModel, setManualModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const selected = providers.find(item => item.id === selectedId) || null;

  const loadProviders = useCallback(async (preferredId?: number) => {
    const result = await llmProvidersApi.list();
    setProviders(result.providers);
    const nextId = preferredId ?? selectedId ?? result.providers[0]?.id ?? null;
    setSelectedId(nextId);
    return nextId;
  }, [selectedId]);

  const loadModels = useCallback(async (id: number | null) => {
    if (!id) {
      setModels([]);
      return;
    }
    const result = await llmProvidersApi.listModels(id);
    setModels(result.models);
  }, []);

  useEffect(() => {
    loadProviders().catch(error => setMessage(errorMessage(error)));
  // Initial load only; selection changes are handled separately.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected || creating) return;
    setName(selected.name);
    setProviderType(selected.provider_type);
    setBaseUrl(selected.base_url);
    setApiKey('');
    setEnabled(selected.enabled);
    loadModels(selected.id).catch(error => setMessage(errorMessage(error)));
  }, [selected, creating, loadModels]);

  const beginCreate = () => {
    setCreating(true);
    setSelectedId(null);
    setName('');
    setProviderType('openai');
    setBaseUrl(defaults.openai);
    setApiKey('');
    setEnabled(true);
    setModels([]);
    setMessage('');
  };

  const save = async (andTest = false) => {
    setBusy(true);
    setMessage('');
    let savedBeforeTest = false;
    try {
      let saved: LlmProviderConnection;
      if (creating) {
        saved = await llmProvidersApi.create({ name, provider_type: providerType, base_url: baseUrl, api_key: apiKey, enabled });
      } else if (selected) {
        saved = await llmProvidersApi.update(selected.id, {
          name, base_url: baseUrl, enabled, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        });
      } else {
        return;
      }
      setCreating(false);
      setApiKey('');
      await loadProviders(saved.id);
      savedBeforeTest = true;
      if (andTest) {
        const result = await llmProvidersApi.test(saved.id);
        setMessage(`Connection saved and verified. ${result.model_count} models reported.`);
        await loadProviders(saved.id);
      } else {
        setMessage('Connection saved.');
      }
    } catch (error) {
      setMessage(savedBeforeTest
        ? `Connection saved, but the test failed: ${errorMessage(error)}`
        : `Failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const sync = async () => {
    if (!selectedId) return;
    setBusy(true);
    setMessage('');
    try {
      const result = await llmProvidersApi.syncModels(selectedId);
      setModels(result.models);
      await loadProviders(selectedId);
      setMessage(`Synchronized ${result.models.length} cached models.`);
    } catch (error) {
      setMessage(`Failed: ${errorMessage(error)}. The previous model cache was preserved.`);
    } finally {
      setBusy(false);
    }
  };

  const addModel = async () => {
    if (!selectedId || !manualModel.trim()) return;
    setBusy(true);
    try {
      await llmProvidersApi.addModel(selectedId, manualModel.trim());
      setManualModel('');
      await loadModels(selectedId);
      setMessage('Manual model added.');
    } catch (error) {
      setMessage(`Failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const toggleModel = async (model: LlmProviderModel) => {
    if (!selectedId) return;
    try {
      await llmProvidersApi.updateModel(selectedId, model.model_id, { enabled: !model.enabled });
      await loadModels(selectedId);
    } catch (error) {
      setMessage(`Failed: ${errorMessage(error)}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-primary mb-2">LLM Providers</h2>
          <p className="text-sm text-muted-foreground">
            Configure OpenAI or Anthropic connections, then synchronize the models available to simulations.
          </p>
        </div>
        <Button onClick={beginCreate}><Plus className="h-4 w-4 mr-2" />Add Provider</Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-4">
        <Card>
          <CardHeader><CardTitle className="text-base">Connections</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {providers.length === 0 && <p className="text-sm text-muted-foreground">No provider configured.</p>}
            {providers.map(provider => (
              <button
                key={provider.id}
                onClick={() => { setCreating(false); setSelectedId(provider.id); setMessage(''); }}
                className={`w-full rounded-md border p-3 text-left text-sm ${selectedId === provider.id && !creating ? 'border-blue-500 bg-blue-500/5' : 'hover:bg-muted/50'}`}
              >
                <span className="font-medium block">{provider.name}</span>
                <span className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                  {provider.last_test_status === 'success' ? <CheckCircle2 className="h-3 w-3 text-green-500" /> :
                    provider.last_test_status === 'failed' ? <XCircle className="h-3 w-3 text-red-500" /> : <Server className="h-3 w-3" />}
                  {provider.provider_type} · {provider.enabled ? 'enabled' : 'disabled'}
                </span>
              </button>
            ))}
          </CardContent>
        </Card>

        <div className="space-y-4">
          {(creating || selected) ? (
            <Card>
              <CardHeader><CardTitle className="text-base">{creating ? 'New Connection' : 'Connection Details'}</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div><label className="text-sm mb-1 block">Name</label><Input value={name} onChange={event => setName(event.target.value)} placeholder="OpenAI Official" /></div>
                  <div>
                    <label className="text-sm mb-1 block">Protocol</label>
                    <select
                      value={providerType}
                      disabled={!creating}
                      onChange={event => {
                        const next = event.target.value as 'openai' | 'anthropic';
                        setProviderType(next);
                        setBaseUrl(defaults[next]);
                      }}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="openai">OpenAI</option>
                      <option value="anthropic">Anthropic</option>
                    </select>
                  </div>
                </div>
                <div><label className="text-sm mb-1 block">Base URL</label><Input value={baseUrl} onChange={event => setBaseUrl(event.target.value)} /></div>
                <div>
                  <label className="text-sm mb-1 block">API Key</label>
                  <Input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={creating ? 'Required' : `Leave blank to keep ${selected?.api_key_masked || 'current key'}`} />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} /> Enabled for new simulations
                </label>
                {selected && (
                  <p className="text-xs text-muted-foreground">
                    Last tested: {selected.last_tested_at ? new Date(selected.last_tested_at).toLocaleString() : 'never'} · Last synced: {selected.last_synced_at ? new Date(selected.last_synced_at).toLocaleString() : 'never'}
                  </p>
                )}
                {selected?.last_error && <p className="text-xs text-red-500">Last test: {selected.last_error}</p>}
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => save(false)} disabled={busy || !name.trim() || (creating && !apiKey.trim())}>Save</Button>
                  <Button variant="outline" onClick={() => save(true)} disabled={busy || !name.trim() || (creating && !apiKey.trim())}>Save & Test</Button>
                  {!creating && <Button variant="outline" onClick={sync} disabled={busy}><RefreshCw className={`h-4 w-4 mr-2 ${busy ? 'animate-spin' : ''}`} />Sync Models</Button>}
                </div>
              </CardContent>
            </Card>
          ) : <Card><CardContent className="p-6 text-sm text-muted-foreground">Select a connection or add a provider.</CardContent></Card>}

          {!creating && selected && (
            <Card>
              <CardHeader><CardTitle className="text-base">Models</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <div className="flex gap-2">
                  <Input value={manualModel} onChange={event => setManualModel(event.target.value)} placeholder="Custom model ID" />
                  <Button variant="outline" onClick={addModel} disabled={busy || !manualModel.trim()}>Add</Button>
                </div>
                {models.length === 0 && <p className="text-sm text-muted-foreground">Synchronize models or add a custom model ID.</p>}
                <div className="divide-y">
                  {models.map(model => (
                    <label key={model.id} className="flex items-center justify-between gap-3 py-3 text-sm">
                      <span>
                        <span className="font-medium block">{model.display_name}</span>
                        <span className="text-xs text-muted-foreground">{model.model_id} · {model.source}{!model.available ? ' · unavailable' : ''}</span>
                      </span>
                      <span className="flex items-center gap-2 whitespace-nowrap">
                        Use in simulation
                        <input type="checkbox" checked={model.enabled} disabled={!model.available && model.source === 'remote'} onChange={() => toggleModel(model)} />
                      </span>
                    </label>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {message && <p className={`text-sm ${message.toLowerCase().includes('fail') ? 'text-red-500' : 'text-green-600'}`}>{message}</p>}
    </div>
  );
}
