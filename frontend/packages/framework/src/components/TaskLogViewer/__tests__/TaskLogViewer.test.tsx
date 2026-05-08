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

import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  flushPromises,
  mockStreamFetch,
  type SseStreamHandle,
} from '../../../../tests/eventSourceStub';
import { QueryWrapper } from '../../../../tests/queryWrapper';
import { TaskLogViewer } from '../TaskLogViewer';

// Stub the log-viewer lib: real one depends on DOM APIs jsdom lacks.
vi.mock('@melloware/react-logviewer', () => ({
  LazyLog: ({ text }: { text: string }) => <pre data-testid="log-output">{text}</pre>,
}));

// Manual mock keeps axios out of the resolution graph.
let _tokenProvider: () => string | null = () => null;
vi.mock('@sep/api', () => ({
  setTokenProvider: (p: () => string | null) => {
    _tokenProvider = p;
  },
  getToken: () => _tokenProvider(),
  refreshAccessToken: vi.fn<() => Promise<string | null>>(),
  apiClient: { get: vi.fn(), defaults: {} },
}));

describe('TaskLogViewer', () => {
  let mock: ReturnType<typeof mockStreamFetch>;

  beforeEach(() => {
    mock = mockStreamFetch();
    mock.install();
    _tokenProvider = () => 'test-token';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  function getHandle(id: string): SseStreamHandle {
    const handle = mock.pending.find((h) => h.url === `/stream-logs/${id}`);
    if (!handle) {
      throw new Error(`No stream handle for /stream-logs/${id}`);
    }
    return handle;
  }

  it('renders accumulated stdout for the first step by default', async () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="7" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    const handle = getHandle('7');
    act(() => {
      handle.pushMessage({ msg: 'line-1\n', step: 'setup', type: 'stdout', offset: 1 });
    });

    await waitFor(() => expect(screen.getByTestId('log-output').textContent).toBe('line-1\n'));
  });

  it('marks the stderr top tab as unread when stderr arrives while on stdout', async () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    const handle = getHandle('1');
    act(() => {
      handle.pushMessage({ msg: 'err\n', step: 'setup', type: 'stderr', offset: 1 });
    });

    await waitFor(() => {
      const stderrTab = screen.getByRole('tab', { name: /stderr/i });
      const dot = stderrTab.querySelector('.MuiBadge-dot');
      expect(dot).toBeTruthy();
      expect(dot?.classList.contains('MuiBadge-invisible')).toBe(false);
    });

    const stderrTab = screen.getByRole('tab', { name: /stderr/i });
    const user = userEvent.setup();
    await user.click(stderrTab);

    // MUI Badge keeps the dot element but toggles an invisible class
    const dotAfter = stderrTab.querySelector('.MuiBadge-dot');
    expect(dotAfter?.classList.contains('MuiBadge-invisible')).toBe(true);
  });

  it('switches pane when clicking the Execution events tab', async () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    const handle = getHandle('1');
    act(() => {
      handle.pushMessage({ msg: 'out\n', step: 'setup', type: 'stdout', offset: 1 });
    });
    await waitFor(() => expect(screen.getByTestId('log-output')).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: /execution events/i }));

    expect(screen.queryByTestId('log-output')).not.toBeInTheDocument();
    expect(screen.getByText(/no execution events yet/i)).toBeInTheDocument();
  });

  it('triggers a blob download when the download button is clicked', async () => {
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="99" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    const handle = getHandle('99');
    act(() => {
      handle.pushMessage({ msg: 'payload', step: 'run', type: 'stdout', offset: 1 });
    });
    await waitFor(() => expect(screen.getByTestId('log-output')).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /download log/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });

  it('renders a status badge when the stream finishes', async () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    const handle = getHandle('1');
    act(() => {
      handle.pushNamed('finish', { status: 'success' });
    });
    await waitFor(() => expect(screen.getByText('Done')).toBeInTheDocument());
  });

  it('resets active step and unread state when taskHistoryId changes', async () => {
    const { rerender } = render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    const first = getHandle('1');
    act(() => {
      first.pushMessage({ msg: 'a\n', step: 'alpha', type: 'stdout', offset: 1 });
    });
    await waitFor(() => expect(screen.getByTestId('log-output').textContent).toBe('a\n'));

    rerender(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="2" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    // Previous step alpha no longer exists; empty state until new data arrives
    expect(screen.queryByTestId('log-output')).not.toBeInTheDocument();
    expect(screen.getByText(/no output yet/i)).toBeInTheDocument();

    const second = getHandle('2');
    act(() => {
      second.pushMessage({ msg: 'b\n', step: 'beta', type: 'stdout', offset: 1 });
    });
    await waitFor(() => expect(screen.getByTestId('log-output').textContent).toBe('b\n'));
    // New step auto-selected, no unread dots from the prior task
    const stepTab = screen.getByRole('tab', { name: /beta/i });
    expect(within(stepTab).queryByRole('status')).toBeNull();
  });

  it('renders the executor-gone error block for 410', async () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    await flushPromises();

    const handle = getHandle('1');
    act(() => {
      handle.pushNamed('sep-error', {
        code: 410,
        detail: { message: 'gone', job_id: 'J-1', executor_name: 'nomad-a' },
      });
    });
    await waitFor(() => expect(screen.getByText('gone')).toBeInTheDocument());
    expect(screen.getByText(/J-1/)).toBeInTheDocument();
    expect(screen.getByText(/nomad-a/)).toBeInTheDocument();
    expect(screen.getByText('Not in executor')).toBeInTheDocument();
  });
});
