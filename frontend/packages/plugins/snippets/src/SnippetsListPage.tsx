import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  CircularProgress,
  Link,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { useSnippets } from './hooks';

/**
 * Snippet-centric list page rendered at `/snippets/`.
 *
 * Renders the snippet entities discovered by the backend (one row per
 * snippet file). Approval/refresh actions remain on the legacy Jinja2
 * surface until SEP-1068 lands them on the JSON API.
 */
export function SnippetsListPage() {
  const navigate = useNavigate();
  const { data: snippets = [], isLoading, error } = useSnippets();

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ py: 4 }}>
        <Alert severity="error">Failed to load snippets: {error.message}</Alert>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Support Snippets
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Pre-approved snippets discovered from disk. Click a row to view its execution form and
        history.
      </Typography>
      {snippets.length === 0 ? (
        <Typography color="text.secondary">No snippets available.</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Filename</TableCell>
              <TableCell>Title</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>Approved</TableCell>
              <TableCell>Reason</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {snippets.map((snippet) => (
              <TableRow
                key={snippet.filename}
                hover
                sx={{ cursor: 'pointer' }}
                onClick={() => navigate(encodeURIComponent(snippet.filename))}
              >
                <TableCell>
                  <Link
                    component="button"
                    type="button"
                    underline="hover"
                    onClick={(event) => {
                      event.stopPropagation();
                      navigate(encodeURIComponent(snippet.filename));
                    }}
                  >
                    {snippet.filename}
                  </Link>
                </TableCell>
                <TableCell>{snippet.title}</TableCell>
                <TableCell>{snippet.description}</TableCell>
                <TableCell>{snippet.is_approved ? 'Yes' : 'No'}</TableCell>
                <TableCell>{snippet.reason}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Box>
  );
}
