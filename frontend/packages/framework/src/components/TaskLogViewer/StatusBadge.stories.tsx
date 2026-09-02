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

import type { Meta, StoryObj } from '@storybook/react-vite';
import { StatusBadge } from './StatusBadge';

const meta: Meta<typeof StatusBadge> = {
  title: 'TaskLogViewer/StatusBadge',
  component: StatusBadge,
  parameters: { layout: 'centered' },
  argTypes: {
    status: {
      control: 'select',
      options: [
        'success',
        'failed',
        'stopped',
        'lost',
        'stale',
        'unlaunchable',
        'stream-error',
        'executor-gone',
      ],
    },
  },
};

export default meta;
type Story = StoryObj<typeof StatusBadge>;

export const Success: Story = { args: { status: 'success' } };
export const Failed: Story = { args: { status: 'failed' } };
export const Stopped: Story = { args: { status: 'stopped' } };
export const Lost: Story = { args: { status: 'lost' } };
export const Stale: Story = { args: { status: 'stale' } };
export const Unlaunchable: Story = { args: { status: 'unlaunchable' } };
export const StreamError: Story = { args: { status: 'stream-error' } };
export const ExecutorGone: Story = { args: { status: 'executor-gone' } };
