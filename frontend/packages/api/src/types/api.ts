// Common API response types — will be generated from OpenAPI later.
// The runtime ApiError class lives in ../errors.ts.

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

// ── Auth ────────────────────────────────────────────────────────────────

/** Response from POST /api/oauth/login and /api/oauth/refresh (SPA shape). */
export interface OAuthTokenResponse {
  accessToken: string;
  expiresIn: number;
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
