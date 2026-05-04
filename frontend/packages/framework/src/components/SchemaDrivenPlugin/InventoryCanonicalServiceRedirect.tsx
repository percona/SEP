import { useEffect } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { inventoryMountPrefix } from './inventoryNestedPaths';

/** Canonical service URL is ``…/services/:id`` (replace deep nested path). */
export function InventoryCanonicalServiceRedirect() {
  const { serviceId } = useParams<{ serviceId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const prefix = inventoryMountPrefix(location.pathname);

  useEffect(() => {
    if (prefix && serviceId) {
      navigate(`${prefix}/services/${serviceId}`, { replace: true });
    }
  }, [navigate, prefix, serviceId]);

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
      <CircularProgress />
    </Box>
  );
}
