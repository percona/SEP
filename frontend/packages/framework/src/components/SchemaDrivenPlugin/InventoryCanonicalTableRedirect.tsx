import { useEffect } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { inventoryMountPrefix } from './inventoryNestedPaths';

/**
 * Canonical table URLs are ``…/tables/:id``. Replace deep nested table paths with that shape.
 */
export function InventoryCanonicalTableRedirect() {
  const { tableId } = useParams<{ tableId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const prefix = inventoryMountPrefix(location.pathname);

  useEffect(() => {
    if (prefix && tableId) {
      navigate(`${prefix}/tables/${tableId}`, { replace: true });
    }
  }, [navigate, prefix, tableId]);

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
      <CircularProgress />
    </Box>
  );
}
