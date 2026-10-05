export interface BoardExitController {
  leave: () => boolean;
  reset: () => void;
}

/**
 * Navigation is deliberately synchronous and independent from board sync.
 * Returning true also lets Android's BackHandler know that the event was handled.
 */
export function createBoardExitController(pop: () => void): BoardExitController {
  let leaving = false;
  return {
    leave: () => {
      if (leaving) return true;
      leaving = true;
      pop();
      return true;
    },
    reset: () => {
      leaving = false;
    },
  };
}
