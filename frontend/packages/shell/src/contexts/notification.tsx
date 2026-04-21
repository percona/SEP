import { useCallback, type ReactNode } from 'react';
import { SnackbarProvider, useSnackbar, type OptionsObject, type SnackbarMessage } from 'notistack';
import { NotistackMuiSnackbar } from '@percona/percona-ui';

// Per-variant auto-dismiss defaults mirror the Jinja2 frontend timers.
const DURATIONS = {
  success: 10_000,
  info: 10_000,
  warning: 20_000,
  error: 30_000,
} as const;

export function NotificationProvider({ children }: { children: ReactNode }) {
  return (
    <SnackbarProvider
      maxSnack={3}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      Components={{
        default: NotistackMuiSnackbar,
        success: NotistackMuiSnackbar,
        error: NotistackMuiSnackbar,
        warning: NotistackMuiSnackbar,
        info: NotistackMuiSnackbar,
      }}
    >
      {children}
    </SnackbarProvider>
  );
}

type ShowOptions = Omit<OptionsObject, 'variant'>;

export function useNotification() {
  const { enqueueSnackbar, closeSnackbar } = useSnackbar();

  const showSuccess = useCallback(
    (msg: SnackbarMessage, options?: ShowOptions) =>
      enqueueSnackbar(msg, { autoHideDuration: DURATIONS.success, ...options, variant: 'success' }),
    [enqueueSnackbar],
  );

  const showError = useCallback(
    (msg: SnackbarMessage, options?: ShowOptions) =>
      enqueueSnackbar(msg, { autoHideDuration: DURATIONS.error, ...options, variant: 'error' }),
    [enqueueSnackbar],
  );

  const showWarning = useCallback(
    (msg: SnackbarMessage, options?: ShowOptions) =>
      enqueueSnackbar(msg, { autoHideDuration: DURATIONS.warning, ...options, variant: 'warning' }),
    [enqueueSnackbar],
  );

  const showInfo = useCallback(
    (msg: SnackbarMessage, options?: ShowOptions) =>
      enqueueSnackbar(msg, { autoHideDuration: DURATIONS.info, ...options, variant: 'info' }),
    [enqueueSnackbar],
  );

  return { showSuccess, showError, showWarning, showInfo, closeSnackbar };
}
