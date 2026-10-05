import { createBoardExitController } from './boardExit';

describe('board exit', () => {
  it('pops immediately without waiting for synchronization', () => {
    const pop = jest.fn();
    const controller = createBoardExitController(pop);

    expect(controller.leave()).toBe(true);
    expect(pop).toHaveBeenCalledTimes(1);
  });

  it('deduplicates rapid taps and resets on the next focus', () => {
    const pop = jest.fn();
    const controller = createBoardExitController(pop);

    controller.leave();
    controller.leave();
    expect(pop).toHaveBeenCalledTimes(1);

    controller.reset();
    controller.leave();
    expect(pop).toHaveBeenCalledTimes(2);
  });
});
