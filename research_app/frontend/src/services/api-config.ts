export const DEFAULT_API_BASE_URL = 'http://localhost:8000';

type LocationLike = Pick<Location, 'hostname' | 'origin'>;

export function isLoopbackHostname(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase().replace(/^\[|\]$/g, '');
  return normalized === 'localhost'
    || normalized.endsWith('.localhost')
    || normalized === '::1'
    || /^127(?:\.\d{1,3}){3}$/.test(normalized);
}

export function resolveApiBaseUrl(
  location: LocationLike,
  configuredUrl = import.meta.env.VITE_API_URL,
): string {
  if (isLoopbackHostname(location.hostname)) {
    return configuredUrl || DEFAULT_API_BASE_URL;
  }
  return location.origin;
}

export const API_BASE_URL = resolveApiBaseUrl(window.location);
