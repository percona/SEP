/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { apiClient, setTokenProvider, type AppListResult } from '@sep/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  useApproveSnippet,
  useRemoveSnippetApproval,
  useSnippetDownload,
  useSnippets,
  useSnippetServiceTypes,
} from './hooks';
import type { SnippetResponse } from './types';

type CapturedHeaders = {
  Authorization?: string;
  get?: (name: string) => string | null | undefined;
  [key: string]: unknown;
};
interface CapturedRequestConfig {
  url?: string;
  method?: string;
  responseType?: string;
  headers?: CapturedHeaders;
  params?: Record<string, unknown>;
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function makeWrapper(client = makeQueryClient()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const originalAdapter = apiClient.defaults.adapter;
const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

describe('useSnippetDownload', () => {
  let lastConfig: CapturedRequestConfig | null = null;
  let blobBody: Blob;
  let createObjectSpy: ReturnType<typeof vi.fn>;
  let revokeObjectSpy: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    lastConfig = null;
    blobBody = new Blob(['#!/bin/sh\necho hi\n'], { type: 'text/x-shellscript' });
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = (
      config: CapturedRequestConfig,
    ) => {
      lastConfig = config;
      return Promise.resolve({
        data: blobBody,
        status: 200,
        statusText: 'OK',
        headers: {
          'content-type': 'text/x-shellscript',
          'content-disposition': 'attachment; filename="hello.sh"',
        },
        config,
        request: {},
      });
    };

    setTokenProvider(() => 'test-access-token');

    createObjectSpy = vi.fn(() => 'blob:mock-url');
    revokeObjectSpy = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectSpy,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: revokeObjectSpy,
      writable: true,
      configurable: true,
    });

    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = originalAdapter;
    setTokenProvider(() => null);
    Object.defineProperty(URL, 'createObjectURL', {
      value: originalCreateObjectURL,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: originalRevokeObjectURL,
      writable: true,
      configurable: true,
    });
    clickSpy.mockRestore();
  });

  it('GETs /apps/snippets/snippet/download?snippet_filename=... with Bearer auth and a blob responseType', async () => {
    const { result } = renderHook(() => useSnippetDownload('hello.sh'), {
      wrapper: makeWrapper(),
    });

    await act(async () => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig).not.toBeNull();
    const captured = lastConfig as CapturedRequestConfig;
    expect(captured.url).toBe('/apps/snippets/snippet/download?snippet_filename=hello.sh');
    expect(captured.method?.toLowerCase()).toBe('get');
    expect(captured.responseType).toBe('blob');

    const headers = captured.headers;
    const auth =
      typeof headers?.get === 'function' ? headers.get('Authorization') : headers?.Authorization;
    expect(auth).toBe('Bearer test-access-token');
  });

  it('encodes nested filenames in the query string', async () => {
    const nested = 'diag/slow-query.sh';
    const { result } = renderHook(() => useSnippetDownload(nested), {
      wrapper: makeWrapper(),
    });

    await act(async () => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    const captured = lastConfig as CapturedRequestConfig;
    expect(captured.url).toBe(
      '/apps/snippets/snippet/download?snippet_filename=diag%2Fslow-query.sh',
    );
    const [path] = (captured.url ?? '').split('?');
    expect(path).not.toContain('%2F');
    expect(path).not.toContain('diag');
  });

  it('reads the response body as a Blob and triggers a download with the snippet filename', async () => {
    const { result } = renderHook(() => useSnippetDownload('long-script.sh'), {
      wrapper: makeWrapper(),
    });

    let downloadAttr: string | null = null;
    let hrefAttr: string | null = null;
    clickSpy.mockImplementation(function clickImpl(this: HTMLAnchorElement) {
      downloadAttr = this.download;
      hrefAttr = this.href;
    });

    await act(async () => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toBeInstanceOf(Blob);
    expect(createObjectSpy).toHaveBeenCalledTimes(1);
    expect(createObjectSpy).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(downloadAttr).toBe('long-script.sh');
    expect(hrefAttr).toContain('blob:mock-url');

    await waitFor(() => {
      expect(revokeObjectSpy).toHaveBeenCalledWith('blob:mock-url');
    });
  });
});

describe('useSnippets', () => {
  let responseBody: unknown;
  let lastConfig: CapturedRequestConfig | null = null;

  beforeEach(() => {
    lastConfig = null;
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = (
      config: CapturedRequestConfig,
    ) => {
      lastConfig = config;
      return Promise.resolve({
        data: responseBody,
        status: 200,
        statusText: 'OK',
        headers: { 'content-type': 'application/json' },
        config,
        request: {},
      });
    };
    setTokenProvider(() => 'test-access-token');
  });

  afterEach(() => {
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = originalAdapter;
    setTokenProvider(() => null);
  });

  it('returns items plus pagination metadata from the envelope', async () => {
    responseBody = {
      items: [{ filename: 'a.sh' }, { filename: 'b.sh' }],
      total: 2,
      offset: 0,
      limit: 50,
    };

    const { result } = renderHook(() => useSnippets(), { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig?.params).toEqual({ offset: 0, limit: 50 });
    expect(result.current.data).toEqual({
      items: [{ filename: 'a.sh' }, { filename: 'b.sh' }],
      pagination: { total: 2, offset: 0, limit: 50 },
    });
  });

  it('forwards offset/limit query params', async () => {
    responseBody = { items: [], total: 0, offset: 50, limit: 50 };

    const { result } = renderHook(() => useSnippets({ offset: 50, limit: 50 }), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig?.params).toEqual({ offset: 50, limit: 50 });
  });

  it('forwards search/approval/service_type filters as query params', async () => {
    responseBody = { items: [], total: 0, offset: 0, limit: 50 };

    const { result } = renderHook(
      () => useSnippets({ search: '  slow  ', approval: 'approved', serviceType: 'mysql' }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig?.params).toMatchObject({
      offset: 0,
      limit: 50,
      search: 'slow',
      approval: 'approved',
      service_type: 'mysql',
    });
  });

  it('omits only blank/undefined filters, forwarding every defined value', async () => {
    responseBody = { items: [], total: 0, offset: 0, limit: 50 };

    // The hook does not special-case "all" — that mapping is the page's job — so a
    // real service type equal to "all" is forwarded verbatim, not dropped.
    const { result } = renderHook(() => useSnippets({ search: '   ', serviceType: 'all' }), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    // toEqual ignores undefined-valued keys, so the blank search is absent while
    // the defined service_type survives.
    expect(lastConfig?.params).toEqual({ offset: 0, limit: 50, service_type: 'all' });
  });

  it('forwards the uncategorized flag as a query param', async () => {
    responseBody = { items: [], total: 0, offset: 0, limit: 50 };

    const { result } = renderHook(() => useSnippets({ uncategorized: true }), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig?.params).toMatchObject({ uncategorized: true });
  });

  it('returns a legacy flat array with pagination null', async () => {
    responseBody = [{ filename: 'a.sh' }];

    const { result } = renderHook(() => useSnippets(), { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual({
      items: [{ filename: 'a.sh' }],
      pagination: null,
    });
  });

  it('drops uncategorized=false rather than sending it as a query param', async () => {
    responseBody = { items: [], total: 0, offset: 0, limit: 50 };

    // The page always passes the boolean, so a `false` (not-uncategorized)
    // selection must resolve to `undefined` and be omitted — never leak as
    // `uncategorized=false`, which the server would treat as a present flag.
    const { result } = renderHook(() => useSnippets({ uncategorized: false }), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig?.params).toEqual({ offset: 0, limit: 50 });
  });

  it('keeps the previous page visible while the next page loads (keepPreviousData)', async () => {
    const page1 = { items: [{ filename: 'p1.sh' }], total: 100, offset: 0, limit: 50 };
    const page2 = { items: [{ filename: 'p2.sh' }], total: 100, offset: 50, limit: 50 };
    let resolveSecond: (() => void) | null = null;

    (apiClient.defaults as unknown as { adapter: unknown }).adapter = (
      config: CapturedRequestConfig,
    ) => {
      const okResponse = (data: unknown) => ({
        data,
        status: 200,
        statusText: 'OK',
        headers: { 'content-type': 'application/json' },
        config,
        request: {},
      });
      if (config.params?.offset === 0) {
        return Promise.resolve(okResponse(page1));
      }
      // Hold the next page in flight so the placeholder window is observable.
      return new Promise((resolve) => {
        resolveSecond = () => resolve(okResponse(page2));
      });
    };
    setTokenProvider(() => 'test-access-token');

    const { result, rerender } = renderHook(({ offset }) => useSnippets({ offset }), {
      wrapper: makeWrapper(),
      initialProps: { offset: 0 },
    });

    await waitFor(() => {
      expect(result.current.data?.items).toEqual([{ filename: 'p1.sh' }]);
    });

    rerender({ offset: 50 });

    // While the second page is in flight, the first page's rows stay visible.
    await waitFor(() => {
      expect(result.current.isPlaceholderData).toBe(true);
    });
    expect(result.current.data?.items).toEqual([{ filename: 'p1.sh' }]);

    await act(async () => {
      resolveSecond?.();
    });

    await waitFor(() => {
      expect(result.current.data?.items).toEqual([{ filename: 'p2.sh' }]);
    });
  });
});

describe('useSnippetServiceTypes', () => {
  let lastConfig: CapturedRequestConfig | null = null;

  beforeEach(() => {
    lastConfig = null;
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = (
      config: CapturedRequestConfig,
    ) => {
      lastConfig = config;
      return Promise.resolve({
        data: { service_types: ['mongodb', 'mysql'], has_uncategorized: true },
        status: 200,
        statusText: 'OK',
        headers: { 'content-type': 'application/json' },
        config,
        request: {},
      });
    };
    setTokenProvider(() => 'test-access-token');
  });

  afterEach(() => {
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = originalAdapter;
    setTokenProvider(() => null);
  });

  it('GETs the whole-dataset service-type facet', async () => {
    const { result } = renderHook(() => useSnippetServiceTypes(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig?.url).toContain('/apps/snippets/service_types');
    expect(result.current.data).toEqual({
      service_types: ['mongodb', 'mysql'],
      has_uncategorized: true,
    });
  });
});

describe('snippet approval optimistic cache', () => {
  const listKey = ['snippets', 'list', { offset: 0, limit: 50 }] as const;

  const unapprovedList = {
    items: [
      { filename: 'check.sh', is_approved: false },
      { filename: 'other.sh', is_approved: false },
    ],
    pagination: { total: 2, offset: 0, limit: 50 },
  } as AppListResult<SnippetResponse>;

  afterEach(() => {
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = originalAdapter;
    setTokenProvider(() => null);
  });

  it('useApproveSnippet flips is_approved on the paginated list cache key', async () => {
    const client = makeQueryClient();
    client.setQueryData(listKey, unapprovedList);

    (apiClient.defaults as unknown as { adapter: unknown }).adapter = () =>
      new Promise(() => {
        /* hang so optimistic data stays visible */
      });
    setTokenProvider(() => 'test-access-token');

    const { result } = renderHook(() => useApproveSnippet('check.sh'), {
      wrapper: makeWrapper(client),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(client.getQueryData(listKey)).toEqual({
        ...unapprovedList,
        items: [{ ...unapprovedList.items[0], is_approved: true }, unapprovedList.items[1]],
      });
    });
  });

  it('useRemoveSnippetApproval clears is_approved on the paginated list cache key', async () => {
    const client = makeQueryClient();
    const approvedList: AppListResult<SnippetResponse> = {
      ...unapprovedList,
      items: unapprovedList.items.map((snippet) => ({ ...snippet, is_approved: true })),
    };
    client.setQueryData(listKey, approvedList);

    (apiClient.defaults as unknown as { adapter: unknown }).adapter = () =>
      new Promise(() => {
        /* hang so optimistic data stays visible */
      });
    setTokenProvider(() => 'test-access-token');

    const { result } = renderHook(() => useRemoveSnippetApproval('check.sh'), {
      wrapper: makeWrapper(client),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(client.getQueryData(listKey)).toEqual({
        ...approvedList,
        items: [{ ...approvedList.items[0], is_approved: false }, approvedList.items[1]],
      });
    });
  });

  it('drops the row and decrements total when approval no longer matches the filter', async () => {
    const client = makeQueryClient();
    // A "not approved" page: approving a row means it no longer belongs here.
    const notApprovedKey = ['snippets', 'list', { offset: 0, limit: 50, approval: 'not_approved' }];
    const notApprovedList = {
      items: [
        { filename: 'check.sh', is_approved: false },
        { filename: 'other.sh', is_approved: false },
      ],
      pagination: { total: 2, offset: 0, limit: 50 },
    } as AppListResult<SnippetResponse>;
    client.setQueryData(notApprovedKey, notApprovedList);

    (apiClient.defaults as unknown as { adapter: unknown }).adapter = () =>
      new Promise(() => {
        /* hang so optimistic data stays visible */
      });
    setTokenProvider(() => 'test-access-token');

    const { result } = renderHook(() => useApproveSnippet('check.sh'), {
      wrapper: makeWrapper(client),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(client.getQueryData(notApprovedKey)).toEqual({
        ...notApprovedList,
        items: [notApprovedList.items[1]],
        pagination: { total: 1, offset: 0, limit: 50 },
      });
    });
  });

  it('drops the row and decrements total when removing approval under the approved filter', async () => {
    const client = makeQueryClient();
    const approvedKey = ['snippets', 'list', { offset: 0, limit: 50, approval: 'approved' }];
    const approvedList = {
      items: [
        { filename: 'check.sh', is_approved: true },
        { filename: 'other.sh', is_approved: true },
      ],
      pagination: { total: 2, offset: 0, limit: 50 },
    } as AppListResult<SnippetResponse>;
    client.setQueryData(approvedKey, approvedList);

    (apiClient.defaults as unknown as { adapter: unknown }).adapter = () =>
      new Promise(() => {
        /* hang so optimistic data stays visible */
      });
    setTokenProvider(() => 'test-access-token');

    const { result } = renderHook(() => useRemoveSnippetApproval('check.sh'), {
      wrapper: makeWrapper(client),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(client.getQueryData(approvedKey)).toEqual({
        ...approvedList,
        items: [approvedList.items[1]],
        pagination: { total: 1, offset: 0, limit: 50 },
      });
    });
  });

  it('flips in place under the "all" filter without touching total', async () => {
    const client = makeQueryClient();
    // No approval param on the key → the "all" view keeps the row, just flipped.
    client.setQueryData(listKey, unapprovedList);

    (apiClient.defaults as unknown as { adapter: unknown }).adapter = () =>
      new Promise(() => {
        /* hang so optimistic data stays visible */
      });
    setTokenProvider(() => 'test-access-token');

    const { result } = renderHook(() => useApproveSnippet('check.sh'), {
      wrapper: makeWrapper(client),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(client.getQueryData(listKey)).toEqual({
        ...unapprovedList,
        items: [{ ...unapprovedList.items[0], is_approved: true }, unapprovedList.items[1]],
        pagination: { total: 2, offset: 0, limit: 50 },
      });
    });
  });

  it('rolls back the paginated list cache when approve fails', async () => {
    const client = makeQueryClient();
    client.setQueryData(listKey, unapprovedList);

    (apiClient.defaults as unknown as { adapter: unknown }).adapter = () =>
      Promise.reject({
        response: { status: 500, data: { detail: 'boom' }, statusText: 'ERR', headers: {} },
        config: {},
        isAxiosError: true,
        toJSON: () => ({}),
        name: 'AxiosError',
        message: 'Request failed',
      });
    setTokenProvider(() => 'test-access-token');

    const { result } = renderHook(() => useApproveSnippet('check.sh'), {
      wrapper: makeWrapper(client),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });

    expect(client.getQueryData(listKey)).toEqual(unapprovedList);
  });
});
