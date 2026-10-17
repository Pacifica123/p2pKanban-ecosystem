// The project board built into the APK: mobile/assets/project-board.json,
// refreshed by `python -B tools/ecosystem/project_board.py vendor mobile`.
let memo: string | null = null;

/** The file byte for byte: it is json.dumps(indent=2, ensure_ascii=False) + "\n", which JSON.stringify(…, 2) reproduces. */
export function buildRaw(): string {
  if (memo === null) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const board: unknown = require('../../../assets/project-board.json');
    memo = `${JSON.stringify(board, null, 2)}\n`;
  }
  return memo;
}
