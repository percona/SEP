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
