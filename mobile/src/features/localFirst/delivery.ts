import type { LocalOperation } from './model';

/** Legacy relay_pending entries are migrated to the durable replica journal. */
export function hasPendingPublication(operation: LocalOperation) {
  return operation.status === 'pending' || operation.status === 'relay_pending';
}
