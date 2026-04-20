import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import ConstructionIcon from '@mui/icons-material/Construction';
import { useLocation } from 'react-router-dom';
import { useNotification } from '../contexts/notification';

export default function PlaceholderPage() {
  const location = useLocation();
  const { showSuccess, showError, showWarning, showInfo } = useNotification();

  // Derive page title from the URL path
  const title = location.pathname
    .split('/')
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' / ');

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        py: 10,
        textAlign: 'center',
      }}
    >
      <ConstructionIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
      <Typography variant="h5" gutterBottom>
        {title || 'Page'}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>
        This section will be implemented during the frontend migration.
      </Typography>

      <Stack direction="row" spacing={2} flexWrap="wrap" justifyContent="center" useFlexGap>
        <Button variant="contained" color="success" onClick={() => showSuccess('Success toast')}>
          Show Success
        </Button>
        <Button variant="contained" color="error" onClick={() => showError('Error toast')}>
          Show Error
        </Button>
        <Button variant="contained" color="warning" onClick={() => showWarning('Warning toast')}>
          Show Warning
        </Button>
        <Button variant="contained" color="info" onClick={() => showInfo('Info toast')}>
          Show Info
        </Button>
      </Stack>
    </Box>
  );
}
