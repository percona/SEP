import AppBar from '@mui/material/AppBar';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Toolbar from '@mui/material/Toolbar';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import MenuIcon from '@mui/icons-material/Menu';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import LogoutIcon from '@mui/icons-material/Logout';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import { useState } from 'react';
import { useAuth } from '../contexts/auth';
import { useThemeMode } from '../contexts/theme';
import { useNavigation } from '../contexts/navigation';

export default function TheHeader() {
  const auth = useAuth();
  const theme = useThemeMode();
  const nav = useNavigation();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  return (
    <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
      <Toolbar>
        <IconButton color="inherit" edge="start" onClick={nav.toggleSidebar} sx={{ mr: 2 }}>
          <MenuIcon />
        </IconButton>

        <Typography
          variant="h6"
          component="div"
          sx={{ fontFamily: '"Poppins", sans-serif', fontWeight: 700 }}
        >
          PERCONA
        </Typography>
        <Typography
          variant="body2"
          sx={{ ml: 1.5, opacity: 0.8, display: { xs: 'none', sm: 'inline' } }}
        >
          Services Enablement Platform
        </Typography>

        <Box sx={{ flexGrow: 1 }} />

        <Tooltip title={theme.isDark ? 'Light mode' : 'Dark mode'}>
          <IconButton color="inherit" onClick={theme.toggle}>
            {theme.isDark ? <LightModeIcon /> : <DarkModeIcon />}
          </IconButton>
        </Tooltip>

        {auth.isAuthenticated && (
          <>
            <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} sx={{ ml: 1 }}>
              <Avatar
                sx={{
                  width: 32,
                  height: 32,
                  bgcolor: 'secondary.main',
                  color: 'secondary.contrastText',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                }}
              >
                {auth.user?.username?.charAt(0).toUpperCase()}
              </Avatar>
            </IconButton>
            <Menu
              anchorEl={anchorEl}
              open={!!anchorEl}
              onClose={() => setAnchorEl(null)}
              slotProps={{ paper: { sx: { minWidth: 200 } } }}
            >
              <Box sx={{ px: 2, py: 1 }}>
                <Typography variant="subtitle2">
                  {auth.user?.fullName || auth.user?.username}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {auth.user?.email}
                </Typography>
              </Box>
              <Divider />
              {import.meta.env.VITE_CASDOOR_USER_PROFILE_URL && (
                <MenuItem
                  component="a"
                  href={import.meta.env.VITE_CASDOOR_USER_PROFILE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setAnchorEl(null)}
                >
                  <ListItemIcon>
                    <AccountCircleIcon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText>Profile</ListItemText>
                </MenuItem>
              )}
              <MenuItem
                onClick={() => {
                  setAnchorEl(null);
                  auth.logout();
                }}
              >
                <ListItemIcon>
                  <LogoutIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Logout</ListItemText>
              </MenuItem>
            </Menu>
          </>
        )}
      </Toolbar>
    </AppBar>
  );
}
