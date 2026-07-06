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

import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Box, CircularProgress, Link as MuiLink, Typography } from '@mui/material';
import { SnippetExecutionAccordion, StandaloneHostSelector } from '@sep/framework';
import { useAlertDetail } from './hooks';

/**
 * Detail page rendered at ``/alerts/troubleshooting/:serviceType/:alertName``.
 *
 * Provides a page-level host selector shared across all snippet accordion
 * cards. Each card drives execution independently — concurrent runs allowed.
 */
export function AlertTroubleshootingDetailPage() {
  const { serviceType, alertName } = useParams<{
    serviceType: string;
    alertName: string;
  }>();
  const navigate = useNavigate();

  const [selectedHost, setSelectedHost] = useState<string>('');
  const { data, isLoading, error } = useAlertDetail(serviceType, alertName);

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
        {error instanceof Error ? error.message : 'Failed to load alert details'}
      </Alert>
    );
  }

  if (!data) {
    return null;
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
        {data.alert.label}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Service type: {serviceType}
      </Typography>

      <StandaloneHostSelector
        value={selectedHost}
        onChange={setSelectedHost}
        sx={{ maxWidth: 480, mb: 4 }}
      />

      {data.snippets.length === 0 ? (
        <Alert severity="info">No diagnostic snippets available for this alert.</Alert>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {data.snippets.map((snippet) =>
            snippet.is_approved ? (
              <SnippetExecutionAccordion
                key={snippet.filename}
                snippetFilename={snippet.filename}
                executorHost={selectedHost}
                title={snippet.title ?? snippet.filename}
                description={snippet.description || undefined}
              />
            ) : (
              <Alert key={snippet.filename} severity="warning">
                {snippet.title ?? snippet.filename} is not approved.
              </Alert>
            ),
          )}
        </Box>
      )}
    </Box>
  );
}
