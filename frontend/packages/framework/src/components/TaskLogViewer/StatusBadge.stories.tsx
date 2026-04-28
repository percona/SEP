import type { Meta, StoryObj } from '@storybook/react-vite';
import { StatusBadge } from './StatusBadge';

const meta: Meta<typeof StatusBadge> = {
  title: 'TaskLogViewer/StatusBadge',
  component: StatusBadge,
  parameters: { layout: 'centered' },
  argTypes: {
    status: {
      control: 'select',
      options: ['success', 'failed', 'stopped', 'lost', 'stream-error', 'executor-gone'],
    },
  },
};

export default meta;
type Story = StoryObj<typeof StatusBadge>;

export const Success: Story = { args: { status: 'success' } };
export const Failed: Story = { args: { status: 'failed' } };
export const Stopped: Story = { args: { status: 'stopped' } };
export const Lost: Story = { args: { status: 'lost' } };
export const StreamError: Story = { args: { status: 'stream-error' } };
export const ExecutorGone: Story = { args: { status: 'executor-gone' } };
