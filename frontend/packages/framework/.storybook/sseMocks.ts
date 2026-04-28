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

type Listener = (event: MessageEvent<string>) => void;

export class StoryEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readonly url: string;
  readonly withCredentials: boolean;
  readyState: number = StoryEventSource.OPEN;
  onmessage: Listener | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onopen: ((ev: Event) => void) | null = null;
  readonly listeners: Record<string, Listener[]> = {};
  closed = false;

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;

    queueMicrotask(() => {
      if (this.closed) {
        return;
      }
      this.onopen?.(new Event('open'));
      const script = scripts.get(url);
      if (script) {
        script(this);
      }
    });
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const fn = listener as Listener;
    (this.listeners[type] ??= []).push(fn);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const fn = listener as Listener;
    const list = this.listeners[type];
    if (!list) {
      return;
    }
    const idx = list.indexOf(fn);
    if (idx >= 0) {
      list.splice(idx, 1);
    }
  }

  close(): void {
    this.closed = true;
    this.readyState = StoryEventSource.CLOSED;
  }

  emitMessage(data: unknown): void {
    if (this.closed) {
      return;
    }
    const event = new MessageEvent('message', { data: JSON.stringify(data) });
    this.onmessage?.(event);
  }

  emitNamed(type: string, data: unknown): void {
    if (this.closed) {
      return;
    }
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    (this.listeners[type] ?? []).forEach((fn) => fn(event));
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
  EventSource: typeof globalThis.EventSource;
  fetch: typeof globalThis.fetch;
}

export function installStorybookSseMocks(): void {
  const g = globalThis as unknown as MockGlobals;
  if (g[INSTALLED_KEY]) {
    return;
  }
  g[INSTALLED_KEY] = true;
  g[ORIGINAL_FETCH_KEY] = g.fetch?.bind(globalThis);

  g.EventSource = StoryEventSource as unknown as typeof globalThis.EventSource;

  g.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    // Longest-prefix match so a more specific registration wins over a more
    // general one (e.g. `/execution-events/sb-success` over `/execution-events`).
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
