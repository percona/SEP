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

import { EventStreamContentType, fetchEventSource } from '@microsoft/fetch-event-source';
import { getToken, refreshAccessToken } from '@sep/api';
import { useEffect, useRef, useState } from 'react';

export type LogType = 'stdout' | 'stderr';

export type StepText = Record<LogType, string>;

export type FinishStatus = 'success' | 'failed' | 'stopped' | 'lost';

export interface StreamError {
  code?: number;
  detail: unknown;
}

export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'finished' | 'error';

export interface TaskLogsState {
  textByStep: Record<string, StepText>;
  stepOrder: string[];
  streamStatus: StreamStatus;
  finishStatus?: FinishStatus;
  error?: StreamError;
}

interface IncomingLog {
  msg: string;
  step: string;
  type: LogType;
  offset: number;
}

// Thrown from onopen after a successful token refresh so onerror can return 0
// (immediate retry) with the new token.
class StreamRetriableAfterRefresh extends Error {}

// Thrown from onopen for terminal open failures so onerror re-throws and stops
// the retry loop permanently. Prevents infinite reconnects after auth failure.
class StreamFatalError extends Error {}

/**
 * SSE-backed log stream for a task history.
 *
 * Single /stream-logs/{id} endpoint covers both running and completed tasks:
 * the server streams historical log lines then emits a `finish` event with
 * terminal status. No REST fallback needed.
 *
 * Uses @microsoft/fetch-event-source so the Bearer token can be attached as a
 * header — the browser EventSource API has no headers option and could only
 * carry cookies, which are not in scope for the SPA OAuth session.
 */
export function useTaskLogs(taskHistoryId: number | string | undefined): TaskLogsState {
  const [textByStep, setTextByStep] = useState<Record<string, StepText>>({});
  const [stepOrder, setStepOrder] = useState<string[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  const [finishStatus, setFinishStatus] = useState<FinishStatus | undefined>();
  const [error, setError] = useState<StreamError | undefined>();

  const offsetsRef = useRef<Record<string, number>>({});
  // Stable ref so onclose can read current streamStatus without re-registering.
  const streamStatusRef = useRef<StreamStatus>('idle');

  useEffect(() => {
    if (taskHistoryId === undefined || taskHistoryId === null || taskHistoryId === '') {
      return;
    }

    // Reset state on id change
    offsetsRef.current = {};
    setTextByStep({});
    setStepOrder([]);
    setFinishStatus(undefined);
    setError(undefined);
    streamStatusRef.current = 'connecting';
    setStreamStatus('connecting');

    const ctrl = new AbortController();
    let currentToken = getToken() ?? '';
    let refreshAttempted = false;
    // Guards all state setters: set to true in cleanup so stale callbacks
    // from an aborted stream cannot write into a subsequent stream's state.
    let disposed = false;

    const url = `/stream-logs/${encodeURIComponent(String(taskHistoryId))}`;

    fetchEventSource(url, {
      signal: ctrl.signal,
      openWhenHidden: true,

      // Custom fetch so we can inject a fresh token on every (re)connect,
      // including after a 401-triggered refresh.
      fetch: (input, init) => {
        // Preserve existing headers (fetchEventSource passes a plain object,
        // but guard against Headers/string[][] just in case).
        const headers = new Headers(init?.headers as HeadersInit | undefined);
        // Only attach the header when a token is available; an empty Bearer
        // value could confuse backend Bearer-detection logic.
        if (currentToken) {
          headers.set('Authorization', `Bearer ${currentToken}`);
        }
        return globalThis.fetch(input as RequestInfo, { ...init, headers });
      },

      onopen: async (response) => {
        if (response.ok && response.headers.get('content-type')?.includes(EventStreamContentType)) {
          // Reset so that future reconnects (e.g. after a network blip that
          // expires the token) are still allowed to attempt a refresh.
          refreshAttempted = false;
          if (!disposed) {
            streamStatusRef.current = 'streaming';
            setStreamStatus('streaming');
          }
          return;
        }
        if (response.status === 401 && !refreshAttempted) {
          refreshAttempted = true;
          const newToken = await refreshAccessToken();
          if (newToken) {
            currentToken = newToken;
            // Throw retriable sentinel so onerror returns 0 (immediate retry)
            // with the updated token.
            throw new StreamRetriableAfterRefresh();
          }
        }
        // Terminal open failure (auth exhausted or non-200 non-401).
        // Set error state here, abort, then throw fatal sentinel so onerror
        // re-throws it and permanently stops the retry loop.
        if (!disposed) {
          const errPayload: StreamError = {
            detail: { message: `Stream open failed with status ${response.status}` },
          };
          setError(errPayload);
          streamStatusRef.current = 'error';
          setStreamStatus('error');
        }
        ctrl.abort();
        throw new StreamFatalError(`Stream open failed: ${response.status}`);
      },

      onmessage: (ev) => {
        if (disposed) {
          return;
        }
        if (ev.data === '') {
          return; // keepalive comment line
        }

        if (ev.event === 'finish') {
          try {
            const data = JSON.parse(ev.data) as { status?: FinishStatus };
            if (data.status) {
              setFinishStatus(data.status);
            }
          } catch {
            // ignore malformed finish payload
          }
          streamStatusRef.current = 'finished';
          setStreamStatus('finished');
          ctrl.abort();
          return;
        }

        if (ev.event === 'sep-error') {
          let payload: StreamError;
          try {
            const parsed = JSON.parse(ev.data) as { code?: number; detail?: unknown };
            payload = { code: parsed.code, detail: parsed.detail ?? ev.data };
          } catch {
            payload = { detail: String(ev.data || 'Unknown stream error') };
          }
          setError(payload);
          streamStatusRef.current = 'error';
          setStreamStatus('error');
          ctrl.abort();
          return;
        }

        // Default message event — log line
        let payload: IncomingLog;
        try {
          payload = JSON.parse(ev.data) as IncomingLog;
        } catch {
          return;
        }
        const { msg, step, type, offset } = payload;
        if (typeof msg !== 'string' || !step || !type || typeof offset !== 'number') {
          return;
        }
        const key = `${step}_${type}`;
        const previousOffset = offsetsRef.current[key];
        if (previousOffset !== undefined && offset <= previousOffset) {
          return;
        }
        offsetsRef.current[key] = offset;

        setTextByStep((prev) => {
          const existing = prev[step] ?? { stdout: '', stderr: '' };
          return {
            ...prev,
            [step]: { ...existing, [type]: existing[type] + msg },
          };
        });
        setStepOrder((prev) => (prev.includes(step) ? prev : [...prev, step]));
      },

      onerror: (err): number | undefined => {
        if (err instanceof StreamRetriableAfterRefresh) {
          // Immediate retry: token was just refreshed, no need to back off.
          return 0;
        }
        if (err instanceof StreamFatalError) {
          // State already set in onopen; re-throw to stop the retry loop.
          throw err;
        }
        // Transient network blip — stay in 'connecting' and let fetchEventSource
        // retry with default 1 000 ms backoff.
        if (!disposed) {
          streamStatusRef.current = 'connecting';
          setStreamStatus('connecting');
        }
        return undefined;
      },

      onclose: () => {
        if (disposed) {
          return;
        }
        // Server closed the connection cleanly without a finish/sep-error frame.
        // Surface as a terminal error only if we haven't already reached a
        // finished/error state (abort() from onmessage arrives after onclose).
        const s = streamStatusRef.current;
        if (s !== 'finished' && s !== 'error') {
          setError({ detail: { message: 'Task log stream connection closed.' } });
          streamStatusRef.current = 'error';
          setStreamStatus('error');
        }
      },
    }).catch(() => {
      // fetchEventSource rejects when AbortController fires — expected on
      // unmount / id change. StreamFatalError re-thrown from onerror also
      // lands here; state is already set so we can ignore it.
    });

    return () => {
      disposed = true;
      ctrl.abort();
    };
  }, [taskHistoryId]);

  return { textByStep, stepOrder, streamStatus, finishStatus, error };
}
