import { Suspense, type ReactNode } from 'react';
import { SnackbarProvider } from 'notistack';
import { NotistackMuiSnackbar } from '@percona/percona-ui';
import CircularProgress from '@mui/material/CircularProgress';
import Box from '@mui/material/Box';
import { AuthProvider } from './contexts/auth';
import { NavigationProvider } from './contexts/navigation';

function LoadingFallback() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
      <CircularProgress />
    </Box>
  );
}

export default function Providers({ children }: { children: ReactNode }) {
  return (
    <SnackbarProvider
      maxSnack={3}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      Components={{ default: NotistackMuiSnackbar, success: NotistackMuiSnackbar, error: NotistackMuiSnackbar, warning: NotistackMuiSnackbar, info: NotistackMuiSnackbar }}
    >
      <AuthProvider>
        <NavigationProvider>
          <Suspense fallback={<LoadingFallback />}>
            {children}
          </Suspense>
        </NavigationProvider>
      </AuthProvider>
    </SnackbarProvider>
  );
}
