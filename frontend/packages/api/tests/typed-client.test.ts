import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setOnUnauthorized, setTokenProvider } from '../src/client';
import { ApiError } from '../src/errors';
import { mainApi, throwOnApiError } from '../src/typed-client';
import { server } from './msw-server';

// openapi-fetch builds absolute URLs from a `baseUrl`. The generated paths
// already include the `/api/...` prefix, and our clients use `baseUrl: ''`,
// so in the browser the Request resolves against the document origin.
// Under Node we need to stub `globalThis.location` so `new URL(path)` works.
beforeEach(() => {
  // Node vitest ships a jsdom-like `location` via `happy-dom`/`jsdom` envs,
  // but this test runs under the default Node env — set it explicitly.
  Object.defineProperty(globalThis, 'location', {
    configurable: true,
    value: { origin: 'http://localhost', href: 'http://localhost/' } as Location,
  });
  setTokenProvider(() => null);
  setOnUnauthorized(() => {});
});

afterEach(() => {
  setTokenProvider(() => null);
  setOnUnauthorized(() => {});
});

describe('typed-client — auth middleware', () => {
  it('attaches Bearer token from the shared provider', async () => {
    setTokenProvider(() => 'shared-token');
    const seen = vi.fn();

    server.use(
      http.get('http://localhost/api/users/me', ({ request }) => {
        seen(request.headers.get('Authorization'));
        return HttpResponse.json({ id: 'x', username: 'u' });
      }),
    );

    await mainApi.GET('/api/users/me');

    expect(seen).toHaveBeenCalledWith('Bearer shared-token');
  });

  it('calls the unauthorized handler on 401 (non-refresh endpoints)', async () => {
    const onUnauth = vi.fn();
    setOnUnauthorized(onUnauth);

    server.use(
      http.get('http://localhost/api/users/me', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 401 }),
      ),
    );

    await mainApi.GET('/api/users/me');

    expect(onUnauth).toHaveBeenCalledOnce();
  });

  it('skips the unauthorized handler on refresh-endpoint 401', async () => {
    const onUnauth = vi.fn();
    setOnUnauthorized(onUnauth);

    server.use(
      http.post('http://localhost/api/oauth/refresh', () =>
        HttpResponse.json({ detail: 'bad' }, { status: 401 }),
      ),
    );

    await mainApi.POST('/api/oauth/refresh');

    expect(onUnauth).not.toHaveBeenCalled();
  });

  it('synthesises a 401 and notifies when the server returns HTML (session expired)', async () => {
    const onUnauth = vi.fn();
    setOnUnauthorized(onUnauth);

    server.use(
      http.get('http://localhost/api/users/me', () =>
        HttpResponse.html('<html>login</html>', { status: 200 }),
      ),
    );

    await expect(throwOnApiError(mainApi.GET('/api/users/me'))).rejects.toSatisfy(
      (err) => err instanceof ApiError && err.status === 401,
    );
    expect(onUnauth).toHaveBeenCalledOnce();
  });
});

describe('throwOnApiError', () => {
  it('returns typed data on 2xx', async () => {
    server.use(
      http.get('http://localhost/api/users/me', () =>
        HttpResponse.json({ id: 'abc', username: 'u' }),
      ),
    );

    const user = await throwOnApiError(mainApi.GET('/api/users/me'));

    expect(user).toMatchObject({ id: 'abc', username: 'u' });
  });

  it('maps a JSON 4xx body to ApiError with status + detail', async () => {
    server.use(
      http.get('http://localhost/api/users/me', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );

    await expect(throwOnApiError(mainApi.GET('/api/users/me'))).rejects.toSatisfy((err) => {
      if (!(err instanceof ApiError)) {
        return false;
      }
      return err.kind === 'http' && err.status === 404 && err.message === 'not found';
    });
  });

  it('maps a network failure to ApiError with kind "network"', async () => {
    server.use(http.get('http://localhost/api/users/me', () => HttpResponse.error()));

    await expect(throwOnApiError(mainApi.GET('/api/users/me'))).rejects.toSatisfy(
      (err) => err instanceof ApiError && err.kind === 'network',
    );
  });

  it('maps a malformed JSON body to ApiError (no raw SyntaxError leaks)', async () => {
    server.use(
      http.get('http://localhost/api/users/me', () =>
        HttpResponse.text('not-json', {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    );

    await expect(throwOnApiError(mainApi.GET('/api/users/me'))).rejects.toBeInstanceOf(ApiError);
  });
});
