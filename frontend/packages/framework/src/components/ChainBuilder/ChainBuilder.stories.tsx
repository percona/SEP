import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react';
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
