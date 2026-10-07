export interface ApiErrorHttp {
  method: string;
  path: string;
  /** Raw response text, as the node sent it (redacted only when a report is built). */
  body: string | null;
  /** `errorId` of a 5xx answered by the node (contracts/error-report/1). */
  errorId: string | null;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;
  http?: ApiErrorHttp;

  constructor(message: string, options: { status: number; code?: string; details?: unknown; http?: ApiErrorHttp }) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
    this.http = options.http;
  }
}
