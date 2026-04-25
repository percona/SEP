// Common API types re-exported from the OpenAPI-generated schemas.
// Hand-written types were removed after SEP-963 Phase 2 codegen landed.
// The runtime ApiError class lives in ../errors.ts.

import type { components } from '../generated/main';

/** Authenticated user profile — `GET /api/users/me`. */
export type User = components['schemas']['CasdoorUser'];

/**
 * Slim OAuth token returned to SPA clients by `POST /api/oauth/login` and
 * `POST /api/oauth/refresh`. Only contains the access token and its TTL —
 * the refresh token rides an `HttpOnly` cookie and is opaque to JS.
 */
export type SPAOAuthTokenResponse = components['schemas']['SPAOAuthTokenResponse'];

/**
 * @deprecated Use `SPAOAuthTokenResponse`. The full `OAuthToken` shape is
 * only returned by the legacy `/oauth/token` endpoint; the SPA uses the
 * cookie-based `/oauth/login` + `/oauth/refresh` flow.
 */
export type OAuthTokenResponse = SPAOAuthTokenResponse;
