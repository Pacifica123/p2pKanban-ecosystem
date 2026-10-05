export interface ApiTransport {
  readonly kind: 'desktop' | 'web';
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export function requestMethod(init?: RequestInit): string {
  return (init?.method ?? 'GET').toUpperCase();
}
