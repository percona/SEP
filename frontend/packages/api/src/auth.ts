import { apiClient } from './client';
import type { SPAOAuthTokenResponse, User } from './types/api';

/**
 * POST /api/oauth/login
 *
 * SPA login. Backend returns the access token + TTL in JSON and sets the
 * refresh token as an `HttpOnly` cookie scoped to `/api/oauth`. The refresh
 * token is never seen by JavaScript.
 */
export async function postLogin(
  username: string,
  password: string,
): Promise<SPAOAuthTokenResponse> {
  const { data } = await apiClient.post<SPAOAuthTokenResponse>('/oauth/login', {
    username,
    password,
  });
  return data;
}

/**
 * POST /api/oauth/refresh
 *
 * Mint a fresh access token from the `HttpOnly` refresh cookie. The cookie is
 * sent automatically by the browser; there is no request body. The backend
 * rotates the cookie on success.
 *
 * Returns the slim SPA shape — `access_token` and `expires_in` only. The
 * refresh token is never in the response body.
 */
export async function postRefresh(): Promise<SPAOAuthTokenResponse> {
  const { data } = await apiClient.post<SPAOAuthTokenResponse>('/oauth/refresh', undefined, {
    withCredentials: true,
  });
  return data;
}

/**
 * GET /api/users/me
 *
 * Fetch the currently authenticated user profile.
 */
export async function fetchCurrentUser(): Promise<User> {
  const { data } = await apiClient.get<User>('/users/me');
  return data;
}
