import Box from '@mui/material/Box';
import Toolbar from '@mui/material/Toolbar';
import Container from '@mui/material/Container';
import { Outlet } from 'react-router-dom';
import TheHeader from './TheHeader';
import TheSidebar from './TheSidebar';

export default function MainLayout() {
  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <TheHeader />
      <TheSidebar />
      <Box component="main" sx={{ flexGrow: 1, minWidth: 0 }}>
        <Toolbar /> {/* spacer for AppBar */}
        <Container maxWidth={false} sx={{ py: 3 }}>
          <Outlet />
        </Container>
      </Box>
    </Box>
  );
}
