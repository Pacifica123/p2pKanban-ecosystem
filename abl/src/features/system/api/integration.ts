import { apiRequest } from '../../../shared/api/client';
import type { DeepLinkIntentSummary, IntegrationCapabilities } from '../../../shared/api/types';

export function getIntegrationCapabilities() {
  return apiRequest<IntegrationCapabilities>('/system/integration-capabilities');
}

export function takeDeepLinkIntents() {
  return apiRequest<DeepLinkIntentSummary[]>('/system/deep-link-intents/take', { method: 'POST' });
}
