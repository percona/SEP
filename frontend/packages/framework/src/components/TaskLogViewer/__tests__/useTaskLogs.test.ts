import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useTaskLogs } from '../../../hooks/useTaskLogs';
import { installMockEventSource, MockEventSource } from '../../../../tests/eventSourceStub';

describe('useTaskLogs', () => {
  beforeEach(() => {
    installMockEventSource();
  });

  afterEach(() => {
    MockEventSource.reset();
  });

  it('opens an EventSource to /stream-logs/{id}', () => {
    renderHook(() => useTaskLogs(42));
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toBe('/stream-logs/42');
    expect(MockEventSource.instances[0].withCredentials).toBe(true);
  });

  it('accumulates log text grouped by step and type', () => {
    const { result } = renderHook(() => useTaskLogs(1));
    const src = MockEventSource.instances[0];

    act(() => {
      src.emitMessage({ msg: 'hello ', step: 'step1', type: 'stdout', offset: 1 });
      src.emitMessage({ msg: 'world', step: 'step1', type: 'stdout', offset: 2 });
      src.emitMessage({ msg: 'boom', step: 'step1', type: 'stderr', offset: 1 });
      src.emitMessage({ msg: 'more', step: 'step2', type: 'stdout', offset: 1 });
    });

    expect(result.current.textByStep.step1.stdout).toBe('hello world');
    expect(result.current.textByStep.step1.stderr).toBe('boom');
    expect(result.current.textByStep.step2.stdout).toBe('more');
    expect(result.current.stepOrder).toEqual(['step1', 'step2']);
  });

  it('dedupes messages whose offset is not greater than the last seen', () => {
    const { result } = renderHook(() => useTaskLogs(1));
    const src = MockEventSource.instances[0];

    act(() => {
      src.emitMessage({ msg: 'a', step: 's', type: 'stdout', offset: 5 });
      src.emitMessage({ msg: 'b', step: 's', type: 'stdout', offset: 5 }); // dup
      src.emitMessage({ msg: 'c', step: 's', type: 'stdout', offset: 4 }); // stale
      src.emitMessage({ msg: 'd', step: 's', type: 'stdout', offset: 6 });
    });

    expect(result.current.textByStep.s.stdout).toBe('ad');
  });

  it('ignores malformed payloads', () => {
    const { result } = renderHook(() => useTaskLogs(1));
    const src = MockEventSource.instances[0];

    act(() => {
      src.emitMessage({ msg: '', step: 's', type: 'stdout', offset: 1 });
      src.emitMessage({ step: 's', type: 'stdout', offset: 2 });
      src.emitMessage({ msg: 'x', step: 's', type: 'stdout' });
    });

    expect(result.current.textByStep).toEqual({});
  });

  it('handles finish event by setting status and closing the stream', () => {
    const { result } = renderHook(() => useTaskLogs(1));
    const src = MockEventSource.instances[0];

    act(() => {
      src.emitNamed('finish', { status: 'success' });
    });

    expect(result.current.finishStatus).toBe('success');
    expect(result.current.streamStatus).toBe('finished');
    expect(src.closed).toBe(true);
  });

  it('handles sep-error event with a 410 payload', () => {
    const { result } = renderHook(() => useTaskLogs(1));
    const src = MockEventSource.instances[0];

    act(() => {
      src.emitNamed('sep-error', {
        code: 410,
        detail: { resource_type: 'job', job_id: 'J', message: 'gone' },
      });
    });

    expect(result.current.error?.code).toBe(410);
    expect(result.current.streamStatus).toBe('error');
    expect(src.closed).toBe(true);
  });

  it('closes the EventSource on unmount', () => {
    const { unmount } = renderHook(() => useTaskLogs(1));
    const src = MockEventSource.instances[0];
    unmount();
    expect(src.closed).toBe(true);
  });

  it('opens a fresh EventSource when the task id changes', () => {
    const { rerender } = renderHook(({ id }) => useTaskLogs(id), {
      initialProps: { id: 1 as number | string },
    });
    expect(MockEventSource.instances).toHaveLength(1);
    const first = MockEventSource.instances[0];

    rerender({ id: 2 });

    expect(first.closed).toBe(true);
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[1].url).toBe('/stream-logs/2');
  });
});
