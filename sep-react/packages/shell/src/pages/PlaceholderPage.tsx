import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import ConstructionIcon from '@mui/icons-material/Construction';
import { useLocation } from 'react-router-dom';

export default function PlaceholderPage() {
  const location = useLocation();

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
      <Typography variant="body2" color="text.secondary">
        This section will be implemented during the frontend migration.
      </Typography>
    </Box>
  );
}
