import { useEffect } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { inventoryMountPrefix } from './inventoryNestedPaths';

/** Canonical schema URL is ``…/schemas/:id`` (replace deep nested path). */
export function InventoryCanonicalSchemaRedirect() {
  const { schemaId } = useParams<{ schemaId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const prefix = inventoryMountPrefix(location.pathname);

  useEffect(() => {
    if (prefix && schemaId) {
      navigate(`${prefix}/schemas/${schemaId}`, { replace: true });
    }
  }, [navigate, prefix, schemaId]);

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
      <CircularProgress />
    </Box>
  );
}
