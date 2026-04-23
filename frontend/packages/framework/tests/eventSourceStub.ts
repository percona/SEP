import { vi } from 'vitest';

type Listener = (event: MessageEvent<string>) => void;

export class MockEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: MockEventSource[] = [];
  readonly url: string;
  readonly withCredentials: boolean;
  readyState: number = MockEventSource.OPEN;
  onmessage: Listener | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onopen: ((ev: Event) => void) | null = null;
  readonly listeners: Record<string, Listener[]> = {};
  closed = false;

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    MockEventSource.instances.push(this);
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
    this.readyState = MockEventSource.CLOSED;
  }

  // Test helpers
  emitMessage(data: unknown): void {
    const event = new MessageEvent('message', { data: JSON.stringify(data) });
    this.onmessage?.(event);
  }

  emitNamed(type: string, data: unknown): void {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    (this.listeners[type] ?? []).forEach((fn) => fn(event));
  }

  static reset(): void {
    MockEventSource.instances = [];
  }
}

export function installMockEventSource(): void {
  MockEventSource.reset();
  vi.stubGlobal('EventSource', MockEventSource);
}
