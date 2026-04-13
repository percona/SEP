import { Outlet } from 'react-router-dom';
import Providers from '../Providers';

export default function RootLayout() {
  return (
    <Providers>
      <Outlet />
    </Providers>
  );
}
