import { apiClient } from './client';
import type { OAuthTokenResponse, User } from './types/api';

/**
 * POST /api/oauth/token
 *
 * Login with username/password. The backend expects
 * application/x-www-form-urlencoded (OAuth2PasswordRequestForm).
 */
export async function postLogin(username: string, password: string): Promise<OAuthTokenResponse> {
  const params = new URLSearchParams();
  params.append('username', username);
  params.append('password', password);

  const { data } = await apiClient.post<OAuthTokenResponse>('/oauth/token', params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  return data;
}

/**
 * POST /api/oauth/refresh
 *
 * Backend signature: `Annotated[str, Body()]` — expects a JSON-encoded string
 * as the request body (not an object wrapping it).
 */
export async function postRefresh(refreshToken: string): Promise<OAuthTokenResponse> {
  const { data } = await apiClient.post<OAuthTokenResponse>(
    '/oauth/refresh',
    JSON.stringify(refreshToken),
    { headers: { 'Content-Type': 'application/json' } },
  );
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
