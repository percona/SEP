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

import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  CircularProgress,
  Link as MuiLink,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { Link } from 'react-router';
import { useAlertGroups } from './hooks';

/**
 * Index page rendered at ``/alerts/troubleshooting``.
 *
 * Displays alerts grouped by service type as accordion sections.
 * Each alert name links to the detail page for that service type
 * and alert combination.
 */
export function AlertTroubleshootingIndexPage() {
  const { data: groups, isLoading, error } = useAlertGroups();

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
        Failed to load alerts: {error instanceof Error ? error.message : 'unknown error'}
      </Alert>
    );
  }

  if (!groups || groups.length === 0) {
    return (
      <Alert severity="info">
        No alerts found. Ensure snippets with alert metadata are available.
      </Alert>
    );
  }

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 3 }}>
        Alert Troubleshooting
      </Typography>

      {groups.map((group) => (
        <Accordion key={group.service_type} disableGutters sx={{ mb: 1 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle1" fontWeight={500}>
              {group.label} ({group.alerts.length})
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            {group.alerts.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No alerts in this group.
              </Typography>
            ) : (
              <Box component="ul" sx={{ m: 0, pl: 2 }}>
                {group.alerts.map((alert) => (
                  <Box component="li" key={alert.name} sx={{ mb: 0.5 }}>
                    <MuiLink component={Link} to={`${group.service_type}/${alert.name}`}>
                      {alert.label}
                    </MuiLink>
                  </Box>
                ))}
              </Box>
            )}
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  );
}
