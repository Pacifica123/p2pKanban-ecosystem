import {mapInSlices, isSyncCanceled} from './uiBudget';

test('long work gives the thread back between slices', async () => {
  let clock = 0;
  const order: string[] = [];
  // A tap queued while the loop runs on the JS thread.
  setTimeout(() => order.push('tap'), 0);
  const work = mapInSlices([1, 2, 3, 4], (value) => { clock += 5; order.push(`item${value}`); return value * 2; },
    {sliceMs: 8, now: () => clock});
  await expect(work).resolves.toEqual([2, 4, 6, 8]);
  // The queued tap ran before the work was finished.
  expect(order.indexOf('tap')).toBeGreaterThan(0);
  expect(order.indexOf('tap')).toBeLessThan(order.length - 1);
});

test('an aborted signal stops the loop with a recognizable cancellation', async () => {
  const controller = new AbortController();
  let seen = 0;
  const work = mapInSlices([1, 2, 3], () => { seen += 1; controller.abort(); }, {signal: controller.signal});
  const error = await work.catch((reason: unknown) => reason);
  expect(isSyncCanceled(error)).toBe(true);
  expect(seen).toBe(1);
});
