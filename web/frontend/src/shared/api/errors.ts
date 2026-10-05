export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;

  constructor(message: string, options: { status: number; code?: string; details?: unknown }) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
  }
}
