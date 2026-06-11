import { useCallback, useRef } from 'react';
import { getToken } from '@sep/api';

export type TaskStreamState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'success'; stdout: string }
  | { status: 'error'; message: string; stdout: string; stderr: string };

interface TaskStreamOptions {
  onStateChange?: (state: TaskStreamState) => void;
  /** Which Nomad task step to listen to (default: 'run-script') */
  step?: string;
  maxRetries?: number;
  retryDelayMs?: number;
}

/**
 * Streams SSE task logs for a dispatched history ID.
 *
 * - `stream(id)` — fire-and-forget; calls `onStateChange` as state transitions occur.
 * - `streamAndWait(id)` — returns a Promise; resolves on success, rejects with Error on failure.
 *   Use inside async submit handlers to keep dialogs in loading state until the task finishes.
 */
export function useTaskStream(opts: TaskStreamOptions = {}) {
  const { onStateChange, step = 'run-script', maxRetries = 8, retryDelayMs = 2000 } = opts;
  const esRef = useRef<EventSource | null>(null);
  const genRef = useRef(0);

  const stop = useCallback(() => {
    genRef.current++;
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const _connect = useCallback(
    (
      historyId: string,
      onDone: (state: TaskStreamState) => void,
    ) => {
      stop();
      const gen = genRef.current;
      onStateChange?.({ status: 'running' });

      let stdoutBuf = '';
      let stderrBuf = '';
      let retries = 0;

      const connect = () => {
        if (genRef.current !== gen) return;
        try {
          const token = getToken();
          const url = `/stream-logs/${encodeURIComponent(historyId)}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
          const es = new EventSource(url);
          esRef.current = es;

          es.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data as string) as Record<string, unknown>;
              const { msg, type, step: msgStep } = data;
              if (msgStep === step && typeof msg === 'string') {
                if (type === 'stdout') stdoutBuf += msg;
                else if (type === 'stderr') stderrBuf += msg;
              }
            } catch (_) { /* ignore non-JSON */ }
          };

          es.addEventListener('finish', (event) => {
            if (genRef.current !== gen || esRef.current !== es) return;
            stop();

            let taskFailed = false;
            try {
              const fd = JSON.parse((event as MessageEvent).data as string) as Record<string, unknown>;
              if (fd.status === 'failed' || (fd.exit_code != null && fd.exit_code !== 0)) {
                taskFailed = true;
              }
            } catch (_) { /* no finish data */ }

            const stderr = stderrBuf.trim();
            const stdout = stdoutBuf.trim();

            if (taskFailed || stderr) {
              const state: TaskStreamState = {
                status: 'error',
                message: stderr || 'Task failed with no error output.',
                stdout,
                stderr,
              };
              onStateChange?.(state);
              onDone(state);
            } else {
              const state: TaskStreamState = { status: 'success', stdout };
              onStateChange?.(state);
              onDone(state);
            }
          });

          es.onerror = () => {
            if (genRef.current !== gen || esRef.current !== es) return;
            es.close();
            esRef.current = null;
            if (retries < maxRetries) {
              retries++;
              setTimeout(connect, retryDelayMs);
            } else {
              stop();
              const state: TaskStreamState = {
                status: 'error',
                message: 'Stream connection failed.',
                stdout: stdoutBuf.trim(),
                stderr: stderrBuf.trim(),
              };
              onStateChange?.(state);
              onDone(state);
            }
          };
        } catch (e) {
          stop();
          const state: TaskStreamState = {
            status: 'error',
            message: String((e as Error)?.message ?? e),
            stdout: '',
            stderr: '',
          };
          onStateChange?.(state);
          onDone(state);
        }
      };

      connect();
    },
    [stop, onStateChange, step, maxRetries, retryDelayMs],
  );

  const stream = useCallback(
    (historyId: string) => {
      if (!historyId) {
        const state: TaskStreamState = { status: 'error', message: 'Missing task history ID.', stdout: '', stderr: '' };
        onStateChange?.(state);
        return;
      }
      _connect(historyId, () => { /* state already sent via onStateChange */ });
    },
    [_connect, onStateChange],
  );

  const streamAndWait = useCallback(
    (historyId: string): Promise<void> => {
      if (!historyId) return Promise.reject(new Error('Missing task history ID.'));
      return new Promise<void>((resolve, reject) => {
        _connect(historyId, (state) => {
          if (state.status === 'success') resolve();
          else reject(new Error(state.status === 'error' ? state.message : 'Task failed'));
        });
      });
    },
    [_connect],
  );

  return { stream, streamAndWait, stop };
}
