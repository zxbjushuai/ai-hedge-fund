/** Legacy direct Go connections remain supported by the backend, but new Web
 * runs use a standard protocol connection to the relay instead. Never rewrite
 * an existing connection's vendor or credentials just to change its UI label.
 */
export function isVisibleLlmConnection(connection: { vendor?: string; provider_type?: string }): boolean {
  return connection.vendor !== 'opencode_go'
    && connection.provider_type !== 'opencode_go'
    && connection.provider_type !== 'opencode_go_responses';
}
