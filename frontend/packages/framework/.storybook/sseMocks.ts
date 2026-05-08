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

// Storybook-only SSE + fetch mocks for TaskLogViewer stories.
//
// Stories declare mock data via `parameters.sseScripts` (URL → script that
// drives the constructed `StoryEventSource`) and `parameters.fetchResponses`
// (URL prefix → JSON body). The global decorator in `preview.tsx` registers
// them additively before the story renders.
//
// The registry is keyed by URL, so stories MUST use unique URLs (in practice,
// unique `taskHistoryId` values). This avoids cross-story contamination
// without per-story teardown — important because Storybook can render
// multiple stories concurrently in docs / composition mode.
//
// Unmocked fetches fall through to the host's real `fetch`. Stories that
// shouldn't hit the network must register every URL they touch.
//
// Implementation note: hooks now use @microsoft/fetch-event-source which calls
// globalThis.fetch (not the browser EventSource constructor). This wrapper
// intercepts fetch for SSE URLs and returns a text/event-stream Response
// backed by a controllable ReadableStream, keeping the story script API
// (emitMessage / emitNamed / close) identical to the prior EventSource-based
// version.

const encoder = new TextEncoder();

/**
 * Stream driver handed to story scripts — same shape as the old EventSource
 * class so existing story scripts work unchanged.
 */
export class StoryEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readonly url: string;
  readonly withCredentials = false;
  readyState: number = StoryEventSource.OPEN;
  closed = false;

  private readonly ctrl: ReadableStreamDefaultController<Uint8Array>;

  constructor(url: string, ctrl: ReadableStreamDefaultController<Uint8Array>) {
    this.url = url;
    this.ctrl = ctrl;
  }

  emitMessage(data: unknown): void {
    if (this.closed) {
      return;
    }
    this.ctrl.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
  }

  emitNamed(type: string, data: unknown): void {
    if (this.closed) {
      return;
    }
    this.ctrl.enqueue(encoder.encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`));
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.readyState = StoryEventSource.CLOSED;
    try {
      this.ctrl.close();
    } catch {
      // already closed
    }
  }
}

const scripts = new Map<string, (es: StoryEventSource) => void>();
const fetchResponses = new Map<string, unknown>();

export function registerSseScript(url: string, script: (es: StoryEventSource) => void): void {
  scripts.set(url, script);
}

export function registerFetchResponse(urlPrefix: string, body: unknown): void {
  fetchResponses.set(urlPrefix, body);
}

// HMR-safe install. Both the install flag and the captured original `fetch`
// live on `globalThis` via well-known symbols so a re-evaluated preview
// module reuses them instead of wrapping our own wrapper.
const INSTALLED_KEY = Symbol.for('@sep/framework.storybook.sseMocks.installed');
const ORIGINAL_FETCH_KEY = Symbol.for('@sep/framework.storybook.sseMocks.originalFetch');

interface MockGlobals {
  [INSTALLED_KEY]?: true;
  [ORIGINAL_FETCH_KEY]?: typeof globalThis.fetch;
  fetch: typeof globalThis.fetch;
}

export function installStorybookSseMocks(): void {
  const g = globalThis as unknown as MockGlobals;
  if (g[INSTALLED_KEY]) {
    return;
  }
  g[INSTALLED_KEY] = true;
  g[ORIGINAL_FETCH_KEY] = g.fetch?.bind(globalThis);

  g.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;

    // SSE script match — exact URL
    if (scripts.has(url)) {
      const script = scripts.get(url)!;
      let streamCtrl!: ReadableStreamDefaultController<Uint8Array>;
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          streamCtrl = c;
        },
      });
      const driver = new StoryEventSource(url, streamCtrl);
      // Schedule the story script after the current microtask so the hook's
      // onopen handler has a chance to run first.
      queueMicrotask(() => script(driver));
      return new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }

    // JSON fetch match — longest-prefix wins
    let bestPrefix: string | undefined;
    for (const prefix of fetchResponses.keys()) {
      if (url.startsWith(prefix) && (!bestPrefix || prefix.length > bestPrefix.length)) {
        bestPrefix = prefix;
      }
    }
    if (bestPrefix !== undefined) {
      return new Response(JSON.stringify(fetchResponses.get(bestPrefix)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const original = g[ORIGINAL_FETCH_KEY];
    if (original) {
      return original(input as RequestInfo, init);
    }
    return new Response('null', { status: 200, headers: { 'Content-Type': 'application/json' } });
  }) as typeof fetch;
}
