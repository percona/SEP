import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, fn, userEvent, within } from 'storybook/test';
import type { StoryEventSource } from '../../../.storybook/sseMocks';
import { TaskLogViewer } from './TaskLogViewer';

const meta: Meta<typeof TaskLogViewer> = {
  title: 'TaskLogViewer/TaskLogViewer',
  component: TaskLogViewer,
  parameters: { layout: 'padded' },
};

export default meta;
type Story = StoryObj<typeof TaskLogViewer>;

const drip = (
  es: StoryEventSource,
  msgs: { msg: string; step: string; type: 'stdout' | 'stderr' }[],
  delayMs: number,
) => {
  msgs.forEach((m, idx) => {
    setTimeout(() => es.emitMessage({ ...m, offset: idx + 1 }), delayMs * (idx + 1));
  });
};

// ── Stories ───────────────────────────────────────────────────────────────

export const Running: Story = {
  args: {
    taskHistoryId: 'sb-running',
    taskStatus: 'RUNNING',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-running': (es: StoryEventSource) => {
        drip(
          es,
          [
            { msg: '[setup] cloning repo…\n', step: 'setup', type: 'stdout' },
            { msg: '[setup] done\n', step: 'setup', type: 'stdout' },
            { msg: '[build] compiling…\n', step: 'build', type: 'stdout' },
            { msg: '[build] warning: unused import\n', step: 'build', type: 'stderr' },
            { msg: '[deploy] uploading…\n', step: 'deploy', type: 'stdout' },
          ],
          400,
        );
      },
      '/stream-logs/sb-running/execution-events': (es: StoryEventSource) => {
        setTimeout(
          () =>
            es.emitMessage({
              timestamp: '2026-04-28T10:00:00Z',
              type: 'STEP_STARTED',
              description: 'setup started',
              step: 'setup',
            }),
          200,
        );
      },
    },
  },
};

export const CompletedSuccess: Story = {
  args: {
    taskHistoryId: 'sb-success',
    taskStatus: 'SUCCESS',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-success': (es: StoryEventSource) => {
        es.emitMessage({
          msg: 'Task finished successfully.\n',
          step: 'main',
          type: 'stdout',
          offset: 1,
        });
        es.emitNamed('finish', { status: 'success' });
      },
    },
    fetchResponses: { '/execution-events/sb-success': [] },
  },
};

export const CompletedFailed: Story = {
  args: {
    taskHistoryId: 'sb-failed',
    taskStatus: 'FAILED',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-failed': (es: StoryEventSource) => {
        es.emitMessage({
          msg: 'Migration failed.\n',
          step: 'migrate',
          type: 'stdout',
          offset: 1,
        });
        es.emitMessage({
          msg: 'Error: deadlock detected.\n',
          step: 'migrate',
          type: 'stderr',
          offset: 2,
        });
        es.emitNamed('finish', { status: 'failed' });
      },
    },
    fetchResponses: { '/execution-events/sb-failed': [] },
  },
};

export const StreamError: Story = {
  args: {
    taskHistoryId: 'sb-stream-error',
    taskStatus: 'RUNNING',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-stream-error': (es: StoryEventSource) => {
        es.emitNamed('sep-error', {
          detail: 'Upstream stream gateway returned 502 Bad Gateway.',
        });
      },
    },
  },
};

export const ExecutorGone: Story = {
  args: {
    taskHistoryId: 'sb-executor-gone',
    taskStatus: 'RUNNING',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-executor-gone': (es: StoryEventSource) => {
        es.emitNamed('sep-error', {
          code: 410,
          detail: {
            message: 'This run is no longer available in the task executor.',
            resource_type: 'task_history',
            resource_id: 'sb-executor-gone',
            job_id: 'job-9f3a',
            evaluation_id: 'eval-ce21',
            executor_name: 'nomad-prod-east-1',
          },
        });
      },
    },
  },
};

export const SteplessEvents: Story = {
  args: {
    taskHistoryId: 'sb-stepless',
    taskStatus: 'SUCCESS',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-stepless': (es: StoryEventSource) => {
        es.emitNamed('finish', { status: 'success' });
      },
    },
    fetchResponses: {
      '/execution-events/sb-stepless': [
        {
          timestamp: '2026-04-28T10:00:00Z',
          type: 'TASK_QUEUED',
          description: 'Task queued for execution',
          step: null,
        },
        {
          timestamp: '2026-04-28T10:00:05Z',
          type: 'TASK_STARTED',
          description: 'Task picked up by executor nomad-prod-east-1',
          step: null,
        },
        {
          timestamp: '2026-04-28T10:00:42Z',
          type: 'TASK_FINISHED',
          description: 'Task finished with status SUCCESS',
          step: null,
        },
      ],
    },
  },
};

export const MultiStepUnreadDots: Story = {
  args: {
    taskHistoryId: 'sb-unread',
    taskStatus: 'RUNNING',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-unread': (es: StoryEventSource) => {
        // First step picked up immediately so it becomes the active one.
        es.emitMessage({ msg: 'alpha line\n', step: 'alpha', type: 'stdout', offset: 1 });
        // Drip into other steps so their tabs gain the unread dot.
        setTimeout(
          () => es.emitMessage({ msg: 'beta line\n', step: 'beta', type: 'stdout', offset: 2 }),
          250,
        );
        setTimeout(
          () => es.emitMessage({ msg: 'gamma line\n', step: 'gamma', type: 'stdout', offset: 3 }),
          500,
        );
        // Stderr arrives on the inactive top tab → unread dot on stderr.
        setTimeout(
          () =>
            es.emitMessage({
              msg: 'whoops\n',
              step: 'alpha',
              type: 'stderr',
              offset: 4,
            }),
          750,
        );
      },
    },
  },
};

export const WrapToggle: Story = {
  args: {
    taskHistoryId: 'sb-wrap',
    taskStatus: 'SUCCESS',
    height: 240,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-wrap': (es: StoryEventSource) => {
        const longLine = 'x'.repeat(400);
        es.emitMessage({
          msg: `${longLine}\n${longLine}\n`,
          step: 'main',
          type: 'stdout',
          offset: 1,
        });
        es.emitNamed('finish', { status: 'success' });
      },
    },
    fetchResponses: { '/execution-events/sb-wrap': [] },
  },
};

// ── Play function: exercise tab switching, unread clearing, download ──────

export const InteractiveSmokeTest: Story = {
  args: {
    taskHistoryId: 'sb-interact',
    taskStatus: 'RUNNING',
    height: 360,
  },
  parameters: {
    sseScripts: {
      '/stream-logs/sb-interact': (es: StoryEventSource) => {
        es.emitMessage({
          msg: 'starting…\n',
          step: 'setup',
          type: 'stdout',
          offset: 1,
        });
        // Stderr arrives while user is on stdout → unread dot expected on stderr.
        es.emitMessage({
          msg: 'warning: noisy\n',
          step: 'setup',
          type: 'stderr',
          offset: 2,
        });
      },
    },
  },
  play: async ({ canvasElement, step }) => {
    const canvas = within(canvasElement);

    await step('stderr top tab gains an unread dot when stderr arrives', async () => {
      const stderrTab = await canvas.findByRole('tab', { name: /stderr/i });
      const dot = stderrTab.querySelector('.MuiBadge-dot');
      await expect(dot).toBeTruthy();
      await expect(dot?.classList.contains('MuiBadge-invisible')).toBe(false);
    });

    await step('clicking stderr clears the unread dot', async () => {
      const stderrTab = await canvas.findByRole('tab', { name: /stderr/i });
      await userEvent.click(stderrTab);
      const dot = stderrTab.querySelector('.MuiBadge-dot');
      await expect(dot?.classList.contains('MuiBadge-invisible')).toBe(true);
    });

    await step('download button invokes URL.createObjectURL with a Blob', async () => {
      const createObjectURL = fn((_blob: Blob) => 'blob:story');
      const revokeObjectURL = fn((_url: string) => undefined);
      const originalCreate = URL.createObjectURL;
      const originalRevoke = URL.revokeObjectURL;
      URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
      URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
      try {
        const download = await canvas.findByRole('button', { name: /download log/i });
        await expect(download).toBeEnabled();
        await userEvent.click(download);
        await expect(createObjectURL).toHaveBeenCalledTimes(1);
        const blobArg = createObjectURL.mock.calls[0]?.[0];
        await expect(blobArg).toBeInstanceOf(Blob);
        await expect(revokeObjectURL).toHaveBeenCalledWith('blob:story');
      } finally {
        URL.createObjectURL = originalCreate;
        URL.revokeObjectURL = originalRevoke;
      }
    });
  },
};
