import React, { Suspense } from 'react';

const RemoteButton = React.lazy(() => import('micro-frontend-vite/RemoteButton'));

export default function App() {
  return (
    <div>
      <h1>Host App in Webpack</h1>
      <Suspense fallback="Carregando...">
        <RemoteButton />
      </Suspense>
    </div>
  );
}
