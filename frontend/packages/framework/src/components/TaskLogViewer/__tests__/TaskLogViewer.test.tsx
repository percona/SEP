import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installMockEventSource, MockEventSource } from '../../../../tests/eventSourceStub';
import { QueryWrapper } from '../../../../tests/queryWrapper';
import { TaskLogViewer } from '../TaskLogViewer';

// Stub the log-viewer lib: real one depends on DOM APIs jsdom lacks.
vi.mock('@melloware/react-logviewer', () => ({
  LazyLog: ({ text }: { text: string }) => <pre data-testid="log-output">{text}</pre>,
}));

function getLogSource(id: string): MockEventSource {
  const src = MockEventSource.instances.find((s) => s.url === `/stream-logs/${id}`);
  if (!src) {
    throw new Error(`No MockEventSource for /stream-logs/${id}`);
  }
  return src;
}

describe('TaskLogViewer', () => {
  beforeEach(() => {
    installMockEventSource();
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })),
    );
  });

  afterEach(() => {
    MockEventSource.reset();
    vi.unstubAllGlobals();
  });

  it('renders accumulated stdout for the first step by default', () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="7" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    const src = getLogSource('7');

    act(() => {
      src.emitMessage({ msg: 'line-1\n', step: 'setup', type: 'stdout', offset: 1 });
    });

    expect(screen.getByTestId('log-output').textContent).toBe('line-1\n');
  });

  it('marks the stderr top tab as unread when stderr arrives while on stdout', async () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    const src = getLogSource('1');

    act(() => {
      src.emitMessage({ msg: 'err\n', step: 'setup', type: 'stderr', offset: 1 });
    });

    const stderrTab = screen.getByRole('tab', { name: /stderr/i });
    const dot = stderrTab.querySelector('.MuiBadge-dot');
    expect(dot).toBeTruthy();
    expect(dot?.classList.contains('MuiBadge-invisible')).toBe(false);

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
    const src = getLogSource('1');
    act(() => {
      src.emitMessage({ msg: 'out\n', step: 'setup', type: 'stdout', offset: 1 });
    });
    expect(screen.getByTestId('log-output')).toBeInTheDocument();

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
    const src = getLogSource('99');
    act(() => {
      src.emitMessage({ msg: 'payload', step: 'run', type: 'stdout', offset: 1 });
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /download log/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });

  it('renders a status badge when the stream finishes', () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    const src = getLogSource('1');
    act(() => {
      src.emitNamed('finish', { status: 'success' });
    });
    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  it('resets active step and unread state when taskHistoryId changes', () => {
    const { rerender } = render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    const first = getLogSource('1');
    act(() => {
      first.emitMessage({ msg: 'a\n', step: 'alpha', type: 'stdout', offset: 1 });
    });
    expect(screen.getByTestId('log-output').textContent).toBe('a\n');

    rerender(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="2" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    // Previous step alpha no longer exists; empty state until new data arrives
    expect(screen.queryByTestId('log-output')).not.toBeInTheDocument();
    expect(screen.getByText(/no output yet/i)).toBeInTheDocument();

    const second = getLogSource('2');
    act(() => {
      second.emitMessage({ msg: 'b\n', step: 'beta', type: 'stdout', offset: 1 });
    });
    expect(screen.getByTestId('log-output').textContent).toBe('b\n');
    // New step auto-selected, no unread dots from the prior task
    const stepTab = screen.getByRole('tab', { name: /beta/i });
    expect(within(stepTab).queryByRole('status')).toBeNull();
  });

  it('renders the executor-gone error block for 410', () => {
    render(
      <QueryWrapper>
        <TaskLogViewer taskHistoryId="1" taskStatus="RUNNING" />
      </QueryWrapper>,
    );
    const src = getLogSource('1');
    act(() => {
      src.emitNamed('sep-error', {
        code: 410,
        detail: { message: 'gone', job_id: 'J-1', executor_name: 'nomad-a' },
      });
    });
    expect(screen.getByText('gone')).toBeInTheDocument();
    expect(screen.getByText(/J-1/)).toBeInTheDocument();
    expect(screen.getByText(/nomad-a/)).toBeInTheDocument();
    expect(screen.getByText('Not in executor')).toBeInTheDocument();
  });
});
