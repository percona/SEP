import { apiClient } from './client';
import type { SPAOAuthTokenResponse, User } from './types/api';

/**
 * POST /api/oauth/login
 *
 * SPA login. Backend runs the Casdoor password grant server-side, stores
 * the refresh token in an `HttpOnly` cookie scoped to `/api/oauth`, and
 * returns the access token (plus TTL) in JSON. The refresh token is never
 * seen by JavaScript.
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
 * Mint a fresh access token from the `HttpOnly` refresh cookie. The cookie
 * is sent automatically by the browser; there is no request body. The
 * backend rotates the cookie on success.
 *
 * Returns the slim SPA shape — `access_token` and `expires_in` only. The
 * refresh token is never in the response body.
 *
 * Note: most callers should funnel through `refreshAccessToken()` in
 * `./client` instead, which single-flights concurrent refresh calls so the
 * cookie is not rotated twice by parallel code paths.
 */
export async function postRefresh(): Promise<SPAOAuthTokenResponse> {
  const { data } = await apiClient.post<SPAOAuthTokenResponse>('/oauth/refresh');
  return data;
}

/**
 * POST /api/oauth/logout
 *
 * End the SPA session server-side: clears/rotates the `HttpOnly` refresh
 * cookie so a subsequent bootstrap refresh cannot mint a new access token,
 * and revokes the access token at Casdoor. Returns 204 on success;
 * callers should still clear local state even if this request fails.
 */
export async function postLogout(): Promise<void> {
  await apiClient.post('/oauth/logout');
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
