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
