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

import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { ChainBuilder, type ChainValue } from './ChainBuilder';

const meta = {
  title: 'Components/ChainBuilder',
  component: ChainBuilder,
} satisfies Meta<typeof ChainBuilder>;

export default meta;

type Story = StoryObj<typeof meta>;

const FIXTURE_TASKS = [
  { name: 'mysql-backup-prod' },
  { name: 'mysql-archive-prod' },
  { name: 'pt-online-schema-change' },
  { name: 'mysql-checksum-prod' },
  { name: 'mysql-restore-staging' },
  { name: 'this-task' },
];

function ControlledChainBuilder(args: Parameters<typeof ChainBuilder>[0]) {
  const [value, setValue] = useState<ChainValue>(args.value);
  return <ChainBuilder {...args} value={value} onChange={setValue} />;
}

export const Empty: Story = {
  args: {
    availableTasks: FIXTURE_TASKS,
    currentTaskName: 'this-task',
    value: { chain_task_names: [], chain_on_failure: false },
    onChange: () => {},
  },
  render: (args) => <ControlledChainBuilder {...args} />,
};

export const WithChain: Story = {
  args: {
    availableTasks: FIXTURE_TASKS,
    currentTaskName: 'this-task',
    value: {
      chain_task_names: ['mysql-backup-prod', 'mysql-checksum-prod'],
      chain_on_failure: false,
    },
    onChange: () => {},
  },
  render: (args) => <ControlledChainBuilder {...args} />,
};

export const ChainOnFailure: Story = {
  args: {
    availableTasks: FIXTURE_TASKS,
    currentTaskName: 'this-task',
    value: {
      chain_task_names: ['mysql-backup-prod', 'mysql-archive-prod', 'mysql-checksum-prod'],
      chain_on_failure: true,
    },
    onChange: () => {},
  },
  render: (args) => <ControlledChainBuilder {...args} />,
};

export const Disabled: Story = {
  args: {
    availableTasks: FIXTURE_TASKS,
    currentTaskName: 'this-task',
    value: {
      chain_task_names: ['mysql-backup-prod'],
      chain_on_failure: false,
    },
    onChange: () => {},
    disabled: true,
  },
  render: (args) => <ControlledChainBuilder {...args} />,
};
