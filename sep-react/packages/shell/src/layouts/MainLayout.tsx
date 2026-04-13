import Box from '@mui/material/Box';
import Toolbar from '@mui/material/Toolbar';
import Container from '@mui/material/Container';
import { Outlet } from 'react-router-dom';
import TheHeader from './TheHeader';
import TheSidebar from './TheSidebar';
import { useNavigation } from '../contexts/navigation';

const DRAWER_WIDTH = 260;

export default function MainLayout() {
  const nav = useNavigation();

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <TheHeader />
      <TheSidebar />
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          transition: (theme) =>
            theme.transitions.create('margin', {
              easing: theme.transitions.easing.sharp,
              duration: theme.transitions.duration.leavingScreen,
            }),
          ml: nav.sidebarOpen ? 0 : `-${DRAWER_WIDTH}px`,
        }}
      >
        <Toolbar /> {/* spacer for AppBar */}
        <Container maxWidth={false} sx={{ py: 3 }}>
          <Outlet />
        </Container>
      </Box>
    </Box>
  );
}
