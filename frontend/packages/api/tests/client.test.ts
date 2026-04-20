import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient, setOnUnauthorized, setTokenProvider } from '../src/client';
import { ApiError } from '../src/errors';
import { server } from './msw-server';

const BASE = 'http://localhost';

beforeEach(() => {
  // Axios default baseURL is '/api' which has no origin under Node.
  // Pin to a full URL so MSW can match requests predictably.
  apiClient.defaults.baseURL = `${BASE}/api`;
  setTokenProvider(() => null);
  setOnUnauthorized(() => {});
});

afterEach(() => {
  setTokenProvider(() => null);
  setOnUnauthorized(() => {});
});

describe('apiClient — Bearer token injection', () => {
  it('attaches Authorization header when provider returns a token', async () => {
    setTokenProvider(() => 'abc123');
    const seen = vi.fn();

    server.use(
      http.get(`${BASE}/api/ping`, ({ request }) => {
        seen(request.headers.get('Authorization'));
        return HttpResponse.json({ ok: true });
      }),
    );

    const res = await apiClient.get('/ping');

    expect(res.status).toBe(200);
    expect(seen).toHaveBeenCalledWith('Bearer abc123');
  });

  it('omits Authorization header when provider returns null', async () => {
    setTokenProvider(() => null);
    const seen = vi.fn();

    server.use(
      http.get(`${BASE}/api/ping`, ({ request }) => {
        seen(request.headers.get('Authorization'));
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiClient.get('/ping');

    expect(seen).toHaveBeenCalledWith(null);
  });
});

describe('apiClient — error normalization', () => {
  it('maps a 404 response to ApiError with kind "http"', async () => {
    server.use(
      http.get(`${BASE}/api/missing`, () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );

    await expect(apiClient.get('/missing')).rejects.toSatisfy((err) => {
      if (!(err instanceof ApiError)) {
        return false;
      }
      return err.kind === 'http' && err.status === 404 && err.message === 'not found';
    });
  });

  it('maps a 500 response to ApiError with kind "http"', async () => {
    server.use(
      http.get(`${BASE}/api/boom`, () => HttpResponse.json({ detail: 'kaboom' }, { status: 500 })),
    );

    await expect(apiClient.get('/boom')).rejects.toSatisfy((err) => {
      if (!(err instanceof ApiError)) {
        return false;
      }
      return err.kind === 'http' && err.status === 500 && err.message === 'kaboom';
    });
  });

  it('maps a network error to ApiError with kind "network"', async () => {
    server.use(http.get(`${BASE}/api/offline`, () => HttpResponse.error()));

    await expect(apiClient.get('/offline')).rejects.toSatisfy((err) => {
      if (!(err instanceof ApiError)) {
        return false;
      }
      return err.kind === 'network';
    });
  });

  it('invokes the unauthorized handler on 401 (non-refresh endpoints)', async () => {
    const onUnauth = vi.fn();
    setOnUnauthorized(onUnauth);

    server.use(
      http.get(`${BASE}/api/protected`, () =>
        HttpResponse.json({ detail: 'nope' }, { status: 401 }),
      ),
    );

    await expect(apiClient.get('/protected')).rejects.toBeInstanceOf(ApiError);
    expect(onUnauth).toHaveBeenCalledOnce();
  });

  it('skips the unauthorized handler on refresh-endpoint 401', async () => {
    const onUnauth = vi.fn();
    setOnUnauthorized(onUnauth);

    server.use(
      http.post(`${BASE}/api/oauth/refresh`, () =>
        HttpResponse.json({ detail: 'bad refresh' }, { status: 401 }),
      ),
    );

    await expect(apiClient.post('/oauth/refresh', '""')).rejects.toBeInstanceOf(ApiError);
    expect(onUnauth).not.toHaveBeenCalled();
  });
});
