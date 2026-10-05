import {hasPendingPublication} from './delivery';
import type {LocalOperation} from './model';
test.each(['pending','relay_pending','failed'])('publication eligibility: %s', status => {
  expect(hasPendingPublication({status} as LocalOperation)).toBe(status !== 'failed');
});
