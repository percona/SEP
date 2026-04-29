import { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { ALERT_CONFIG_QUERY_KEY } from '@sep/api';
import { AlertOnFailField, ALERT_ON_FAIL_FIELD_NAME } from './AlertOnFailField';

interface StoryArgs {
  available: boolean;
  defaultValue: boolean;
}

function StoryHarness({ available, defaultValue }: StoryArgs) {
  // Per-story QueryClient pre-seeded with the alert-config response so the
  // hook resolves synchronously without hitting the network.
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } },
    });
    qc.setQueryData(ALERT_CONFIG_QUERY_KEY, { available });
    return qc;
  }, [available]);

  useEffect(() => () => queryClient.clear(), [queryClient]);

  const { control, watch } = useForm();
  const value = watch(ALERT_ON_FAIL_FIELD_NAME);

  return (
    <QueryClientProvider client={queryClient}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <AlertOnFailField control={control} defaultValue={defaultValue} />
        <code style={{ fontSize: 12, opacity: 0.6 }}>alert_on_fail: {String(value ?? false)}</code>
      </div>
    </QueryClientProvider>
  );
}

const meta: Meta<typeof StoryHarness> = {
  title: 'Framework/AlertOnFailField',
  component: StoryHarness,
  parameters: { layout: 'padded' },
  args: { available: true, defaultValue: false },
  argTypes: {
    available: {
      control: 'boolean',
      description: 'Mocked `/config/alerts` `available` flag',
    },
    defaultValue: {
      control: 'boolean',
      description: 'Initial form value (only honored when `available` is true)',
    },
  },
};
export default meta;

type Story = StoryObj<typeof StoryHarness>;

/** Provider configured: enabled checkbox with the affirmative tooltip. */
export const ProvidersAvailable: Story = {
  args: { available: true, defaultValue: false },
};

/** No providers configured: disabled checkbox prompting setup via tooltip. */
export const ProvidersUnavailable: Story = {
  args: { available: false, defaultValue: false },
};

/** Edit-mode use case: pre-checked because the existing task had it on. */
export const PreCheckedDefault: Story = {
  args: { available: true, defaultValue: true },
};
