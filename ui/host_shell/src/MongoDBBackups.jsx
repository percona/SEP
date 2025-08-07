import React, { Suspense } from 'react';

const RemoteButton = React.lazy(() => import('micro-frontend-vite/RemoteButton'));
const MyTable = React.lazy(() => import('micro-frontend-vite/MyTable'));

export default function MongoDBBackups() {
  return (
    <div>
      <h1>Host App in Webpack</h1>
      <Suspense fallback="Carregando...">
        <RemoteButton />
        <MyTable />
      </Suspense>
    </div>
  );
}
