import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useForm, type Control, type FieldValues } from 'react-hook-form';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

const useAlertConfigMock = vi.fn();

vi.mock('@sep/api', () => ({
  useAlertConfig: () => useAlertConfigMock(),
}));

import { AlertOnFailField, ALERT_ON_FAIL_FIELD_NAME } from './AlertOnFailField';

type AlertConfigState = {
  data?: { available: boolean };
  isLoading: boolean;
  isError?: boolean;
};

function setAlertConfig(state: AlertConfigState) {
  useAlertConfigMock.mockReturnValue({ isError: false, ...state });
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

function Harness({
  defaultValue,
  onSubmit,
  controlSpy,
}: {
  defaultValue?: boolean;
  onSubmit?: (values: Record<string, unknown>) => void;
  controlSpy?: (control: Control<FieldValues>) => void;
}) {
  const { control, handleSubmit } = useForm();
  controlSpy?.(control);
  return (
    <form onSubmit={handleSubmit((v) => onSubmit?.(v))}>
      <AlertOnFailField control={control} defaultValue={defaultValue} />
      <button type="submit">submit</button>
    </form>
  );
}

function renderHarness(ui: ReactNode) {
  return render(<QueryClientProvider client={makeQueryClient()}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  useAlertConfigMock.mockReset();
});

describe('AlertOnFailField', () => {
  it('uses the snake_case form field name expected by the API', () => {
    expect(ALERT_ON_FAIL_FIELD_NAME).toBe('alert_on_fail');
  });

  it('renders an enabled checkbox when providers are configured', () => {
    setAlertConfig({ data: { available: true }, isLoading: false });
    renderHarness(<Harness />);

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    expect(checkbox).not.toBeDisabled();
    expect(checkbox).not.toBeChecked();
  });

  it('renders a disabled checkbox when no providers are configured', () => {
    setAlertConfig({ data: { available: false }, isLoading: false });
    renderHarness(<Harness />);

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    expect(checkbox).toBeDisabled();
    expect(checkbox).not.toBeChecked();
  });

  it('keeps the checkbox disabled while the availability query is loading', () => {
    setAlertConfig({ data: undefined, isLoading: true });
    renderHarness(<Harness />);

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    expect(checkbox).toBeDisabled();
  });

  it('disables the checkbox when the availability query errors', () => {
    setAlertConfig({ data: undefined, isLoading: false, isError: true });
    renderHarness(<Harness />);

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    expect(checkbox).toBeDisabled();
  });

  it('honors defaultValue=true when providers are available', () => {
    setAlertConfig({ data: { available: true }, isLoading: false });
    renderHarness(<Harness defaultValue />);

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    expect(checkbox).toBeChecked();
  });

  it('clears defaultValue=true when providers are unavailable at mount', async () => {
    setAlertConfig({ data: { available: false }, isLoading: false });
    let capturedControl: Control<FieldValues> | undefined;
    renderHarness(
      <Harness
        defaultValue
        controlSpy={(c) => {
          capturedControl = c;
        }}
      />,
    );

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    expect(checkbox).toBeDisabled();
    await waitFor(() => expect(checkbox).not.toBeChecked());
    // Form state, not just rendered checkbox, must be cleared.
    expect(capturedControl?._formValues.alert_on_fail).toBe(false);
  });

  it('clears the value when providers become unavailable mid-session', async () => {
    setAlertConfig({ data: { available: true }, isLoading: false });
    const user = userEvent.setup();
    let capturedControl: Control<FieldValues> | undefined;
    const { rerender } = renderHarness(
      <Harness
        controlSpy={(c) => {
          capturedControl = c;
        }}
      />,
    );

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    await user.click(checkbox);
    expect(checkbox).toBeChecked();

    setAlertConfig({ data: { available: false }, isLoading: false });
    rerender(
      <QueryClientProvider client={makeQueryClient()}>
        <Harness
          controlSpy={(c) => {
            capturedControl = c;
          }}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(checkbox).not.toBeChecked());
    expect(checkbox).toBeDisabled();
    expect(capturedControl?._formValues.alert_on_fail).toBe(false);
  });

  it('keeps defaultValue=true after a delayed available=true query resolution', async () => {
    setAlertConfig({ data: undefined, isLoading: true });
    const { rerender } = renderHarness(<Harness defaultValue />);

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    // While loading, the field is disabled but the initial form value is preserved.
    expect(checkbox).toBeDisabled();

    setAlertConfig({ data: { available: true }, isLoading: false });
    rerender(
      <QueryClientProvider client={makeQueryClient()}>
        <Harness defaultValue />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(checkbox).not.toBeDisabled());
    expect(checkbox).toBeChecked();
  });

  it('submits the toggled value under the alert_on_fail key', async () => {
    setAlertConfig({ data: { available: true }, isLoading: false });
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    renderHarness(<Harness onSubmit={onSubmit} />);

    const checkbox = screen.getByRole('checkbox', { name: /Alert on failure/i });
    await user.click(checkbox);
    await user.click(screen.getByRole('button', { name: 'submit' }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ alert_on_fail: true }));
  });
});
