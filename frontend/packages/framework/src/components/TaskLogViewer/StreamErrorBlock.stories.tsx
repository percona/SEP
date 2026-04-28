import type { Meta, StoryObj } from '@storybook/react-vite';
import { StreamErrorBlock } from './StreamErrorBlock';

const meta: Meta<typeof StreamErrorBlock> = {
  title: 'TaskLogViewer/StreamErrorBlock',
  component: StreamErrorBlock,
  parameters: { layout: 'padded' },
};

export default meta;
type Story = StoryObj<typeof StreamErrorBlock>;

export const Generic: Story = {
  args: {
    error: {
      detail: 'Upstream stream gateway returned 502 Bad Gateway.',
    },
  },
};

export const GenericStructured: Story = {
  args: {
    error: {
      detail: {
        code: 'ESOCKETTIMEDOUT',
        url: '/stream-logs/123',
        attempts: 3,
      },
    },
  },
};

export const ExecutorGone: Story = {
  args: {
    error: {
      code: 410,
      detail: {
        message: 'This run is no longer available in the task executor.',
        resource_type: 'task_history',
        resource_id: '12345',
        job_id: 'job-9f3a',
        evaluation_id: 'eval-ce21',
        executor_name: 'nomad-prod-east-1',
      },
    },
  },
};
