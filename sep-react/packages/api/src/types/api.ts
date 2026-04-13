import type { AxiosError } from 'axios';

// Common API response types — will be generated from OpenAPI later

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  perPage: number;
}

export interface ApiErrorResponse {
  detail: string;
  statusCode: number;
}

export type ApiError = AxiosError<ApiErrorResponse>;

// ── Auth ────────────────────────────────────────────────────────────────

/** Response from POST /api/oauth/token and /api/oauth/refresh */
export interface OAuthTokenResponse {
  accessToken: string;
  idToken: string;
  refreshToken: string;
  tokenType: string;
  expiresIn: number;
  scope: string;
}

/** User profile returned by GET /api/users/me */
export interface User {
  id: string;
  username: string;
  email: string;
  firstName: string;
  lastName: string;
  fullName: string;
  isAdmin: boolean;
  isActive: boolean;
  isForbidden: boolean;
  isDeleted: boolean;
  owner: string;
  createdTime: string;
  updatedTime: string;
}
