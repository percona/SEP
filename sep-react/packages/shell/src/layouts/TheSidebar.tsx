import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Drawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Collapse from '@mui/material/Collapse';
import Divider from '@mui/material/Divider';
import Toolbar from '@mui/material/Toolbar';
import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';
import SettingsIcon from '@mui/icons-material/Settings';
import { useNavigation, type NavItem } from '../contexts/navigation';

const DRAWER_WIDTH = 260;

function NavGroup({ item }: { item: NavItem }) {
  const location = useLocation();
  const navigate = useNavigate();
  const isChildActive = item.children?.some((c) => c.to === location.pathname) ?? false;
  const [open, setOpen] = useState(isChildActive);

  return (
    <>
      <ListItemButton onClick={() => setOpen((prev) => !prev)} sx={{ borderRadius: 2, mb: 0.5 }}>
        <ListItemIcon>
          <item.icon />
        </ListItemIcon>
        <ListItemText primary={item.title} />
        {open ? <ExpandLess /> : <ExpandMore />}
      </ListItemButton>
      <Collapse in={open} timeout="auto" unmountOnExit>
        <List disablePadding>
          {item.children?.map((child) => (
            <ListItemButton
              key={child.title}
              selected={location.pathname === child.to}
              onClick={() => child.to && navigate(child.to)}
              sx={{ pl: 4, borderRadius: 2, mb: 0.5 }}
            >
              <ListItemIcon>
                <child.icon />
              </ListItemIcon>
              <ListItemText primary={child.title} />
            </ListItemButton>
          ))}
        </List>
      </Collapse>
    </>
  );
}

export default function TheSidebar() {
  const nav = useNavigation();
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <Drawer
      variant="persistent"
      open={nav.sidebarOpen}
      sx={{
        width: nav.sidebarOpen ? DRAWER_WIDTH : 0,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          boxSizing: 'border-box',
        },
      }}
    >
      <Toolbar /> {/* spacer for AppBar */}
      <List sx={{ px: 1, py: 1, flexGrow: 1 }}>
        {nav.items.map((item) =>
          item.children ? (
            <NavGroup key={item.title} item={item} />
          ) : (
            <ListItemButton
              key={item.title}
              selected={location.pathname === item.to}
              onClick={() => item.to && navigate(item.to)}
              sx={{ borderRadius: 2, mb: 0.5 }}
            >
              <ListItemIcon>
                <item.icon />
              </ListItemIcon>
              <ListItemText primary={item.title} />
            </ListItemButton>
          ),
        )}
      </List>
      <Divider />
      <List sx={{ px: 1 }}>
        <ListItemButton
          onClick={() => navigate('/settings')}
          sx={{ borderRadius: 2 }}
        >
          <ListItemIcon>
            <SettingsIcon />
          </ListItemIcon>
          <ListItemText primary="Settings" />
        </ListItemButton>
      </List>
    </Drawer>
  );
}
