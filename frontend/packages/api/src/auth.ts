import { apiClient } from './client';
import type { OAuthTokenResponse, User } from './types/api';

/**
 * POST /api/oauth/login
 *
 * SPA login. Backend runs the Casdoor password grant server-side, stores
 * the refresh token in an HttpOnly cookie, and returns the access token
 * (plus TTL) in JSON.
 */
export async function postLogin(username: string, password: string): Promise<OAuthTokenResponse> {
  const { data } = await apiClient.post<OAuthTokenResponse>('/oauth/login', { username, password });
  return data;
}

/**
 * POST /api/oauth/logout
 *
 * Clears the refresh cookie server-side and revokes the access token at
 * Casdoor. Requires the Bearer access token (authenticated call).
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
