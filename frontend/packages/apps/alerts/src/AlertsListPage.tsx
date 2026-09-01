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
import { Link } from 'react-router';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  Link as MuiLink,
  Paper,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import SettingsIcon from '@mui/icons-material/Settings';
import { useAuth } from '@sep/api';
import { useAlertBackups, useAlertsIndex } from './hooks';
import { AlertsWizard } from './AlertsWizard';
import type { AlertTemplate, WizardMode } from './types';
import { formatTimestamp } from './utils';

const SEVERITY_COLORS: Record<string, 'default' | 'info' | 'warning' | 'error'> = {
  info: 'info',
  warning: 'warning',
  critical: 'error',
};

/**
 * Index page rendered at /alerts/templates.
 *
 * Lists alert templates grouped by service type. Provides actions for pushing
 * to PMM, restoring from backup, and configuring PagerDuty via the
 * AlertsWizard dialog.
 */
export function AlertsListPage() {
  const { canMutate } = useAuth();
  const { data, isLoading, error } = useAlertsIndex();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [wizardMode, setWizardMode] = useState<WizardMode | null>(null);

  // Source the restore picker from the full (paginated) backups list rather
  // than the index's 10-item `recent_backups` slice, so older backups can be
  // restored too. Deferred until the restore wizard is actually opened.
  const restoreBackups = useAlertBackups(wizardMode === 'restore');

  const openWizard = (mode: WizardMode) => setWizardMode(mode);
  const closeWizard = () => setWizardMode(null);

  const toggleTemplate = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const toggleGroup = (templateNames: string[]) => {
    const allSelected = templateNames.every((n) => selected.has(n));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        templateNames.forEach((n) => next.delete(n));
      } else {
        templateNames.forEach((n) => next.add(n));
      }
      return next;
    });
  };

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

  const allTemplates: AlertTemplate[] = (data?.groups ?? []).flatMap((g) => g.templates);
  const selectedTemplates = allTemplates.filter((t) => selected.has(t.name));
  const pagerdutyConfigured = data?.pagerduty?.configured ?? false;

  return (
    <Box>
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          mb: 3,
          flexWrap: 'wrap',
          gap: 1,
        }}
      >
        <Typography variant="h4">Alert Templates</Typography>

        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {!data?.pmm_connected && (
            <Alert severity="warning" sx={{ py: 0 }}>
              PMM not connected
            </Alert>
          )}
          {canMutate && (
            <>
              <Button
                variant="contained"
                startIcon={<NotificationsActiveIcon />}
                disabled={selected.size === 0 || !data?.pmm_connected}
                onClick={() => openWizard('push')}
              >
                Push Selected ({selected.size})
              </Button>
              <Button
                variant="outlined"
                onClick={() => openWizard('restore')}
                disabled={(data?.recent_backups ?? []).length === 0}
              >
                Restore from Backup
              </Button>
              <Button
                variant="outlined"
                startIcon={<SettingsIcon />}
                onClick={() => openWizard('pagerduty')}
                disabled={!data?.pmm_connected}
                color={pagerdutyConfigured ? 'success' : 'primary'}
              >
                {pagerdutyConfigured ? 'PagerDuty Configured ✓' : 'Configure PagerDuty'}
              </Button>
            </>
          )}
        </Box>
      </Box>

      {/* Template groups */}
      {(data?.groups ?? []).length === 0 ? (
        <Alert severity="info">No alert templates found.</Alert>
      ) : (
        (data?.groups ?? []).map((group) => {
          const groupNames = group.templates.map((t) => t.name);
          const allChecked = groupNames.length > 0 && groupNames.every((n) => selected.has(n));
          const someChecked = groupNames.some((n) => selected.has(n));

          return (
            <Accordion key={group.service_type} disableGutters sx={{ mb: 1 }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  {/* Selection exists only to feed Push Selected, so both go together. */}
                  {canMutate && (
                    <Checkbox
                      checked={allChecked}
                      indeterminate={someChecked && !allChecked}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleGroup(groupNames);
                      }}
                      size="small"
                      inputProps={{ 'aria-label': `Select all ${group.label} templates` }}
                    />
                  )}
                  <Typography variant="subtitle1" fontWeight={500}>
                    {group.label} ({group.templates.length})
                  </Typography>
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                {group.templates.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    No templates in this group.
                  </Typography>
                ) : (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                    {group.templates.map((template) => (
                      <Box
                        key={template.name}
                        sx={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 1,
                          py: 0.5,
                        }}
                      >
                        {canMutate && (
                          <Checkbox
                            checked={selected.has(template.name)}
                            onChange={() => toggleTemplate(template.name)}
                            size="small"
                            inputProps={{ 'aria-label': template.name }}
                          />
                        )}
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography variant="body2" fontWeight={500}>
                              {template.name}
                            </Typography>
                            <Chip
                              label={template.severity}
                              size="small"
                              color={SEVERITY_COLORS[template.severity] ?? 'default'}
                            />
                            {template.in_pmm && (
                              <Chip
                                label="In PMM"
                                size="small"
                                color="success"
                                variant="outlined"
                              />
                            )}
                          </Box>
                          <Typography variant="caption" color="text.secondary" display="block">
                            {template.description}
                          </Typography>
                        </Box>
                      </Box>
                    ))}
                  </Box>
                )}
              </AccordionDetails>
            </Accordion>
          );
        })
      )}

      {/* Recent backups */}
      {(data?.recent_backups ?? []).length > 0 && (
        <Paper variant="outlined" sx={{ mt: 3, p: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Recent Backups
          </Typography>
          <Divider sx={{ mb: 1 }} />
          {(data?.recent_backups ?? []).map((backup) => (
            <Box
              key={backup.id}
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                py: 0.5,
              }}
            >
              <Typography variant="body2">{formatTimestamp(backup.created_at)}</Typography>
              <MuiLink component={Link} to={`backup/${backup.id}`} variant="body2">
                View
              </MuiLink>
            </Box>
          ))}
        </Paper>
      )}

      {/* Wizard dialog */}
      {wizardMode !== null && (
        <AlertsWizard
          mode={wizardMode}
          open
          onClose={closeWizard}
          selectedTemplates={selectedTemplates}
          backups={restoreBackups.data ?? data?.recent_backups ?? []}
          pagerdutyConfigured={pagerdutyConfigured}
          onPushSuccess={() => setSelected(new Set())}
        />
      )}
    </Box>
  );
}
