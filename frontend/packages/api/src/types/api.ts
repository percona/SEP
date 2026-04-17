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
