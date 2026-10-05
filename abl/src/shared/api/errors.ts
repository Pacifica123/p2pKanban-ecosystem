export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(message: string, input: { status: number; code?: string; details?: unknown }) {
    super(message);
    this.name = 'ApiError';
    this.status = input.status;
    this.code = input.code;
    this.details = input.details;
  }
}
