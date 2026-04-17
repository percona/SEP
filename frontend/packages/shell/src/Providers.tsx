import { Suspense, type ReactNode } from 'react';
import CircularProgress from '@mui/material/CircularProgress';
import Box from '@mui/material/Box';
import { AuthProvider } from './contexts/auth';
import { NavigationProvider } from './contexts/navigation';
import { NotificationProvider } from './contexts/notification';

function LoadingFallback() {
  return (
    <Box
      sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}
    >
      <CircularProgress />
    </Box>
  );
}

export default function Providers({ children }: { children: ReactNode }) {
  return (
    <NotificationProvider>
      <AuthProvider>
        <NavigationProvider>
          <Suspense fallback={<LoadingFallback />}>{children}</Suspense>
        </NavigationProvider>
      </AuthProvider>
    </NotificationProvider>
  );
}
