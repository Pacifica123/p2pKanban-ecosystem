import { apiRequest } from '@/shared/api/client';
import type {
  CreateExportJobRequest,
  CreateImportJobRequest,
  IntegrationOperationStubResponse,
  IntegrationProviderCatalogResponse,
  IntegrationProviderDetailResponse,
  WebhookReceiptResponse,
} from '@/shared/types/api';

export function getIntegrationProviders() {
  return apiRequest<IntegrationProviderCatalogResponse>('/integrations/providers');
}

export function getIntegrationProvider(providerKey: string) {
  return apiRequest<IntegrationProviderDetailResponse>(`/integrations/providers/${providerKey}`);
}

export function createImportJob(input: CreateImportJobRequest) {
  return apiRequest<IntegrationOperationStubResponse>('/integrations/import-jobs', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function createExportJob(input: CreateExportJobRequest) {
  return apiRequest<IntegrationOperationStubResponse>('/integrations/export-jobs', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function sendWebhookStub(providerKey: string, payload: Record<string, unknown>) {
  return apiRequest<WebhookReceiptResponse>(`/integrations/webhooks/${providerKey}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
