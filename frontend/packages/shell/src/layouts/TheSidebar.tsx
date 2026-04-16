import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Collapse from '@mui/material/Collapse';
import Divider from '@mui/material/Divider';
import Toolbar from '@mui/material/Toolbar';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import useMediaQuery from '@mui/material/useMediaQuery';
import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';
import SettingsIcon from '@mui/icons-material/Settings';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import ViewQuiltIcon from '@mui/icons-material/ViewQuilt';
import MenuBookIcon from '@mui/icons-material/MenuBook';
import GitHubIcon from '@mui/icons-material/GitHub';
import { useNavigation, type NavItem } from '../contexts/navigation';

const DRAWER_WIDTH_EXPANDED = 260;
const DRAWER_WIDTH_COLLAPSED = 64;

const PMM_URL = import.meta.env.VITE_PMM_URL;

function NavGroup({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const isChildActive = item.children?.some((c) => c.to === location.pathname) ?? false;
  const [open, setOpen] = useState(isChildActive);

  // Auto-collapse groups when sidebar is in mini mode
  useEffect(() => {
    if (collapsed) {
      setOpen(false);
    } else if (isChildActive) {
      setOpen(true);
    }
  }, [collapsed, isChildActive]);

  const button = (
    <ListItemButton
      onClick={() => {
        if (collapsed && item.children?.[0]?.to) {
          navigate(item.children[0].to);
          onNavigate?.();
        } else {
          setOpen((prev) => !prev);
        }
      }}
      selected={collapsed && isChildActive}
      sx={{ px: 0, borderRadius: 2, mb: 0.5, justifyContent: collapsed ? 'center' : 'flex-start' }}
    >
      <ListItemIcon sx={{ minWidth: collapsed ? 0 : 40, justifyContent: 'center' }}>
        <item.icon />
      </ListItemIcon>
      {!collapsed && <ListItemText primary={item.title} />}
      {!collapsed && (open ? <ExpandLess /> : <ExpandMore />)}
    </ListItemButton>
  );

  return (
    <>
      {collapsed ? (
        <Tooltip title={item.title} placement="right">
          {button}
        </Tooltip>
      ) : (
        button
      )}
      <Collapse in={open && !collapsed} timeout="auto" unmountOnExit>
        <List disablePadding>
          {item.children?.map((child) => (
            <ListItemButton
              key={child.title}
              selected={location.pathname === child.to}
              onClick={() => {
                if (child.to) {
                  navigate(child.to);
                  onNavigate?.();
                }
              }}
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

function NavLeaf({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();

  const button = (
    <ListItemButton
      selected={location.pathname === item.to}
      onClick={() => {
        if (item.to) {
          navigate(item.to);
          onNavigate?.();
        }
      }}
      sx={{ px: 0, borderRadius: 2, mb: 0.5, justifyContent: collapsed ? 'center' : 'flex-start' }}
    >
      <ListItemIcon sx={{ minWidth: collapsed ? 0 : 40, justifyContent: 'center' }}>
        <item.icon />
      </ListItemIcon>
      {!collapsed && <ListItemText primary={item.title} />}
    </ListItemButton>
  );

  return collapsed ? (
    <Tooltip title={item.title} placement="right">
      {button}
    </Tooltip>
  ) : (
    button
  );
}

function ExternalLink({
  href,
  title,
  icon: Icon,
  collapsed,
}: {
  href: string;
  title: string;
  icon: React.ElementType;
  collapsed: boolean;
}) {
  const button = (
    <ListItemButton
      component="a"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      sx={{ borderRadius: 2, mb: 0.5, justifyContent: collapsed ? 'center' : 'flex-start' }}
    >
      <ListItemIcon sx={{ minWidth: collapsed ? 0 : 40, justifyContent: 'center' }}>
        <Icon />
      </ListItemIcon>
      {!collapsed && (
        <>
          <ListItemText primary={title} />
          <OpenInNewIcon fontSize="small" sx={{ opacity: 0.6 }} />
        </>
      )}
    </ListItemButton>
  );

  return collapsed ? (
    <Tooltip title={title} placement="right">
      {button}
    </Tooltip>
  ) : (
    button
  );
}

function DrawerContent({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const nav = useNavigation();
  const navigate = useNavigate();
  const location = useLocation();

  const handleNav = (to: string) => {
    navigate(to);
    onNavigate?.();
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', flexGrow: 1, overflowY: 'auto' }}>
      <List sx={{ px: 1, py: 1, flexGrow: 1 }}>
        {nav.items.map((item) =>
          item.children ? (
            <NavGroup key={item.title} item={item} collapsed={collapsed} onNavigate={onNavigate} />
          ) : (
            <NavLeaf key={item.title} item={item} collapsed={collapsed} onNavigate={onNavigate} />
          ),
        )}
        {PMM_URL && (
          <ExternalLink href={PMM_URL} title="PMM" icon={ViewQuiltIcon} collapsed={collapsed} />
        )}
      </List>
      <Divider />
      <List sx={{ px: 1 }}>
        <ListItemButton
          selected={location.pathname === '/settings'}
          onClick={() => handleNav('/settings')}
          sx={{ borderRadius: 2, justifyContent: collapsed ? 'center' : 'flex-start' }}
        >
          <ListItemIcon sx={{ minWidth: collapsed ? 0 : 40, justifyContent: 'center' }}>
            <SettingsIcon />
          </ListItemIcon>
          {!collapsed && <ListItemText primary="Settings" />}
        </ListItemButton>
        <ExternalLink
          href="https://docs.percona.com"
          title="Documentation"
          icon={MenuBookIcon}
          collapsed={collapsed}
        />
        <ExternalLink
          href="https://github.com/percona/SEP"
          title="GitHub"
          icon={GitHubIcon}
          collapsed={collapsed}
        />
      </List>
      {!collapsed && (
        <Box sx={{ px: 2, py: 1.5 }}>
          <Typography variant="caption" color="text.secondary">
            © {new Date().getFullYear()} Percona LLC
          </Typography>
        </Box>
      )}
    </Box>
  );
}

export default function TheSidebar() {
  const nav = useNavigation();
  const isNarrow = useMediaQuery((t: { breakpoints: { down: (key: string) => string } }) =>
    t.breakpoints.down('md'),
  );

  // Narrow: permanent mini (icons-only) + temporary overlay when toggled open
  // Wide: permanent drawer, toggle between mini and full
  const collapsed = isNarrow || !nav.sidebarOpen;
  const width = collapsed ? DRAWER_WIDTH_COLLAPSED : DRAWER_WIDTH_EXPANDED;

  return (
    <>
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH_COLLAPSED,
          flexShrink: 0,
          whiteSpace: 'nowrap',
          display: isNarrow ? undefined : 'none',
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH_COLLAPSED,
            boxSizing: 'border-box',
            overflowX: 'hidden',
          },
        }}
      >
        <Toolbar />
        <DrawerContent collapsed />
      </Drawer>
      {isNarrow ? (
        <Drawer
          variant="temporary"
          open={nav.sidebarOpen}
          onClose={nav.toggleSidebar}
          ModalProps={{ keepMounted: true }}
          sx={{
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH_EXPANDED,
              boxSizing: 'border-box',
            },
          }}
        >
          <Toolbar />
          <DrawerContent collapsed={false} onNavigate={nav.toggleSidebar} />
        </Drawer>
      ) : (
        <Drawer
          variant="permanent"
          sx={{
            width,
            flexShrink: 0,
            whiteSpace: 'nowrap',
            '& .MuiDrawer-paper': {
              width,
              boxSizing: 'border-box',
              overflowX: 'hidden',
              transition: (theme) =>
                theme.transitions.create('width', {
                  easing: theme.transitions.easing.sharp,
                  duration: theme.transitions.duration.enteringScreen,
                }),
            },
          }}
        >
          <Toolbar />
          <DrawerContent collapsed={collapsed} />
        </Drawer>
      )}
    </>
  );
}
