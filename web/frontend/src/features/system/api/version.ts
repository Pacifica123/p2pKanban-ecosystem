import { apiRequest } from '@/shared/api/client';

export interface BackendVersion {
  status: string;
  service: string;
  version: string;
  env: string;
}

export function getBackendVersion() {
  return apiRequest<BackendVersion>('/health');
}

