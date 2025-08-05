import React, { Suspense } from 'react';

const MicroFrontendVite = React.lazy(() => import('micro-frontend-vite/Button'));

export default function App() {
  return (
    <div>
      <h1>Host App in Webpack</h1>
      <Suspense fallback="Carregando...">
        <MicroFrontendVite />
      </Suspense>
    </div>
  );
}
