/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  CircularProgress,
  Divider,
  Link as MuiLink,
  Paper,
  Typography,
} from '@mui/material';
import { useAlertBackupDetail } from './hooks';
import { formatTimestamp } from './utils';

/**
 * Detail page rendered at /alerts/templates/backup/:backupId.
 *
 * Displays the contents of a specific alert backup: templates, rules,
 * contact points, folders, and notification policy receiver.
 */
export function AlertsDetailPage() {
  const { backupId } = useParams<{ backupId: string }>();
  const navigate = useNavigate();
  const id = backupId !== undefined ? Number(backupId) : undefined;

  const invalidId = id === undefined || Number.isNaN(id);
  const { data, isLoading, error } = useAlertBackupDetail(invalidId ? undefined : id);

  if (invalidId) {
    return <Alert severity="error">Invalid backup ID.</Alert>;
  }

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error">
        {error instanceof Error ? error.message : 'Failed to load backup detail'}
      </Alert>
    );
  }

  if (!data) {
    return <Alert severity="error">Backup not found.</Alert>;
  }

  return (
    <Box>
      <MuiLink
        component="button"
        type="button"
        onClick={() => navigate('..')}
        sx={{ mb: 2, display: 'inline-block' }}
      >
        ← Back to alerts
      </MuiLink>

      <Typography variant="h4" sx={{ mb: 0.5 }}>
        Backup #{data.id}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Created: {formatTimestamp(data.created_at)}
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Templates ({data.templates.length})
        </Typography>
        <Divider sx={{ mb: 1 }} />
        {data.templates.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No templates in this backup.
          </Typography>
        ) : (
          data.templates.map((t, i) => (
            <Box key={`${t.name}-${i}`} sx={{ py: 0.25 }}>
              <Typography variant="body2" fontWeight={500}>
                {t.name}
              </Typography>
              {t.summary && (
                <Typography variant="caption" color="text.secondary">
                  {t.summary}
                </Typography>
              )}
            </Box>
          ))
        )}
      </Paper>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Rules ({data.rules.length})
        </Typography>
        <Divider sx={{ mb: 1 }} />
        {data.rules.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No rules in this backup.
          </Typography>
        ) : (
          data.rules.map((r, i) => (
            <Typography key={`${r.title}-${i}`} variant="body2" sx={{ py: 0.25 }}>
              {r.title}
            </Typography>
          ))
        )}
      </Paper>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Contact Points ({data.contact_points.length})
        </Typography>
        <Divider sx={{ mb: 1 }} />
        {data.contact_points.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No contact points in this backup.
          </Typography>
        ) : (
          data.contact_points.map((cp, i) => (
            <Typography key={`${cp.name}-${i}`} variant="body2" sx={{ py: 0.25 }}>
              {cp.name} ({cp.type})
            </Typography>
          ))
        )}
      </Paper>

      {data.folders.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Folders ({data.folders.length})
          </Typography>
          <Divider sx={{ mb: 1 }} />
          {data.folders.map((f, i) => (
            <Typography key={`${f.title}-${i}`} variant="body2" sx={{ py: 0.25 }}>
              {f.title}
            </Typography>
          ))}
        </Paper>
      )}

      {data.notification_policy_receiver && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
            Notification Policy Receiver
          </Typography>
          <Typography variant="body2">{data.notification_policy_receiver}</Typography>
        </Paper>
      )}
    </Box>
  );
}
