import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios';

export type ApiErrorKind = 'network' | 'timeout' | 'canceled' | 'http' | 'unknown';

export interface ApiErrorDetails {
  kind: ApiErrorKind;
  status?: number;
  code?: string;
  message: string;
  url?: string;
  method?: string;
  data?: unknown;
}

/**
 * Structured error surfaced to UI consumers. Wraps the original AxiosError
 * so detailed inspection is still possible, but exposes a stable shape that
 * components can rely on without knowing about axios internals.
 */
export class ApiError extends Error implements ApiErrorDetails {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly code?: string;
  readonly url?: string;
  readonly method?: string;
  readonly data?: unknown;
  readonly original?: unknown;

  constructor(details: ApiErrorDetails, original?: unknown) {
    super(details.message);
    this.name = 'ApiError';
    this.kind = details.kind;
    this.status = details.status;
    this.code = details.code;
    this.url = details.url;
    this.method = details.method;
    this.data = details.data;
    this.original = original;
  }
}

function messageFromPayload(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const obj = payload as Record<string, unknown>;
    const detail = obj.detail ?? obj.message ?? obj.error;
    if (typeof detail === 'string') {
      return detail;
    }
  }
  return fallback;
}

export function normalizeAxiosError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }

  if (axios.isCancel(error)) {
    return new ApiError({ kind: 'canceled', message: 'Request canceled' }, error);
  }

  if (error instanceof AxiosError) {
    const config = error.config as AxiosRequestConfig | undefined;
    const response = error.response as AxiosResponse | undefined;
    const url = config?.url;
    const method = config?.method?.toUpperCase();

    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return new ApiError(
        { kind: 'timeout', code: error.code, message: 'Request timed out', url, method },
        error,
      );
    }

    if (response) {
      const status = response.status;
      return new ApiError(
        {
          kind: 'http',
          status,
          code: error.code,
          message: messageFromPayload(response.data, `HTTP ${status}`),
          url,
          method,
          data: response.data,
        },
        error,
      );
    }

    return new ApiError(
      {
        kind: 'network',
        code: error.code,
        message: error.message || 'Network error',
        url,
        method,
      },
      error,
    );
  }

  const message = error instanceof Error ? error.message : 'Unknown error';
  return new ApiError({ kind: 'unknown', message }, error);
}
