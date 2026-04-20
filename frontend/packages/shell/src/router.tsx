import { lazy } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import RootLayout from './layouts/RootLayout';
import MainLayout from './layouts/MainLayout';
import AuthGuard from './components/AuthGuard';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const PlaceholderPage = lazy(() => import('./pages/PlaceholderPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

// Schema-driven plugins — each is a single lazy import
const ChecksumsPlugin = lazy(() =>
  import('@sep/checksums').then((m) => ({ default: m.ChecksumsPlugin })),
);

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      {
        path: '/login',
        element: <LoginPage />,
      },
      {
        path: '/',
        element: (
          <AuthGuard>
            <MainLayout />
          </AuthGuard>
        ),
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'inventory', element: <PlaceholderPage /> },
          { path: 'tasks', element: <PlaceholderPage /> },
          { path: 'snippets', element: <PlaceholderPage /> },
          { path: 'atw', element: <PlaceholderPage /> },
          { path: 'dipper', element: <PlaceholderPage /> },
          { path: 'alerts/templates', element: <PlaceholderPage /> },
          { path: 'alerts/troubleshooting', element: <PlaceholderPage /> },
          { path: 'schema-change/alters', element: <PlaceholderPage /> },
          // Checksums — schema-driven plugin (handles its own sub-routes)
          { path: 'schema-change/checksums/*', element: <ChecksumsPlugin /> },
          { path: 'backups/mysql', element: <PlaceholderPage /> },
          { path: 'backups/mongodb', element: <PlaceholderPage /> },
          { path: 'backups/postgresql', element: <PlaceholderPage /> },
          { path: 'archive', element: <PlaceholderPage /> },
          { path: 'reports', element: <PlaceholderPage /> },
          { path: 'settings', element: <PlaceholderPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
      {
        path: '*',
        element: <Navigate to="/" replace />,
      },
    ],
  },
]);
