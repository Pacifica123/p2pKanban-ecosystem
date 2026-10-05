import { apiRequest } from '../../../shared/api/client';
import type { BackendVersion } from '../../../shared/api/types';

export function getBackendVersion() {
  return apiRequest<BackendVersion>('/health');
}
