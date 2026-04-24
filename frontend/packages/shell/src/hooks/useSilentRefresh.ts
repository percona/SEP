import { useEffect, useRef } from 'react';
import { refreshAccessToken } from '@sep/api';

interface Options {
  /** Current access token. Used as the effect key so a new timer is
   *  scheduled on every rotation (the token changes, the TTL may not). */
  accessToken: string | null;
  /** Access token TTL from the last login/refresh response (seconds). */
  expiresIn: number | null;
  /** Called when the scheduled refresh call fails. */
  onFailure: () => void;
  /** Seconds before expiry to fire the refresh. Defaults to 60. */
  leadSeconds?: number;
}

const MIN_DELAY_MS = 10_000;

/**
 * Schedule a silent refresh ahead of the access-token expiry. Success-path
 * state updates happen via the ``setOnRefreshed`` callback wired into the
 * API client — this hook only triggers the shared single-flight refresh so
 * concurrent refreshes from the 401 retry interceptor and the bootstrap
 * path cannot rotate the cookie twice and invalidate each other.
 *
 * Keying the effect on ``accessToken`` (not just ``expiresIn``) is load-
 * bearing: the backend typically returns the same TTL on every refresh, so
 * ``setExpiresIn(300)`` is a no-op and would not re-arm the timer — the
 * token, however, changes on every rotation.
 */
export function useSilentRefresh({
  accessToken,
  expiresIn,
  onFailure,
  leadSeconds = 60,
}: Options): void {
  const onFailureRef = useRef(onFailure);
  onFailureRef.current = onFailure;

  useEffect(() => {
    if (!accessToken || expiresIn === null) {
      return;
    }
    const delay = Math.max((expiresIn - leadSeconds) * 1000, MIN_DELAY_MS);
    const timer = setTimeout(async () => {
      const newToken = await refreshAccessToken();
      if (!newToken) {
        onFailureRef.current();
      }
    }, delay);
    return () => clearTimeout(timer);
  }, [accessToken, expiresIn, leadSeconds]);
}
