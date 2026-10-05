import { apiRequest } from '@/shared/api/client';
import type {
  CreateImportExecutionRequest,
  CreateImportPreviewRequest,
  CreatePortableExportRequest,
  ImportExecutionResponse,
  ImportExportCapabilitiesResponse,
  ImportPreviewResponse,
  PortableExportResponse,
} from '@/shared/types/api';

export function getImportExportCapabilities() {
  return apiRequest<ImportExportCapabilitiesResponse>('/integrations/import-export/capabilities');
}

export function createPortableExport(input: CreatePortableExportRequest) {
  return apiRequest<PortableExportResponse>('/integrations/import-export/exports', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function previewImportBundle(input: CreateImportPreviewRequest) {
  return apiRequest<ImportPreviewResponse>('/integrations/import-export/imports/preview', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function createImportExecution(input: CreateImportExecutionRequest) {
  return apiRequest<ImportExecutionResponse>('/integrations/import-export/imports', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}
