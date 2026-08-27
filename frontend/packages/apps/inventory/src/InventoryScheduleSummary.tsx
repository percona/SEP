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

import ScheduleIcon from '@mui/icons-material/Schedule';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import {
  describePeriod,
  formatAbsoluteTime,
  formatRelativeTime,
  selectSchedule,
  useScheduledTasksForApp,
} from '@sep/framework';

const INVENTORY_SYNC_TASK_NAME = 'inventory-sync';

export interface InventoryScheduleSummaryProps {
  /**
   * Whether scheduling is available for the app. When false the summary
   * renders nothing: schedules cannot exist, so polling the API and showing an
   * empty-state would only mislead. Mirrors the gating on the Schedules button.
   */
  schedulingEnabled: boolean;
  /** Disable list polling. Used by stories/tests. */
  disablePolling?: boolean;
}

/**
 * At-a-glance, app-level summary of inventory-sync schedules, surfaced on the
 * nodes page so users can see whether anything is scheduled without opening the
 * Schedules screen.
 *
 * Inventory's sync schedule is app-level (a single periodic task that may own
 * several syncer schedules) rather than per-node, so a per-row schedule cell
 * does not apply; this is a compact header summary instead. When several
 * schedules are configured it surfaces the soonest one (via `selectSchedule`)
 * and notes how many more exist. Recurrence/next-run wording is shared with the
 * scheduled-tasks table and detail summary via the framework period helpers.
 */
export function InventoryScheduleSummary({
  schedulingEnabled,
  disablePolling = false,
}: InventoryScheduleSummaryProps) {
  const {
    periodicTasks: allPeriodicTasks,
    isLoading,
    isError,
  } = useScheduledTasksForApp('inventory', { disablePolling });
  // The Inventory plugin's task list also carries `inventory-collection`
  // (tombstone cleanup); scope this summary to sync so its cadence never
  // gets reported as the sync cadence.
  const periodicTasks = allPeriodicTasks.filter((p) => p.task === INVENTORY_SYNC_TASK_NAME);

  // Scheduling off → no schedules can exist; render nothing rather than poll the
  // API and show a misleading empty-state. The hook is still called above to
  // keep hook order stable across renders.
  if (!schedulingEnabled) {
    return null;
  }

  let content;
  if (isLoading) {
    content = (
      <Typography variant="body2" color="text.secondary">
        Checking schedules…
      </Typography>
    );
  } else if (isError) {
    // Don't claim "no schedules" when the lookup failed — that empty-state is a
    // factual assertion (AC #3) and a transient fetch error must not fake it.
    content = (
      <Typography variant="body2" color="text.secondary" data-testid="inv-schedule-summary-error">
        Schedule status unavailable
      </Typography>
    );
  } else if (periodicTasks.length === 0) {
    content = (
      <Typography variant="body2" color="text.secondary" data-testid="inv-schedule-summary-empty">
        No inventory-sync schedules configured
      </Typography>
    );
  } else {
    const selected = selectSchedule(periodicTasks);
    const period = selected ? describePeriod(selected) : undefined;
    const extra = periodicTasks.length - 1;
    content = (
      <Typography variant="body2" data-testid="inv-schedule-summary-scheduled">
        <Typography component="span" variant="body2" fontWeight={500}>
          Sync scheduled
        </Typography>
        {period &&
          (period.tooltip ? (
            <Tooltip title={period.tooltip}>
              <Typography component="span" variant="body2">
                {` · ${period.display}`}
              </Typography>
            </Tooltip>
          ) : (
            <Typography component="span" variant="body2">
              {` · ${period.display}`}
            </Typography>
          ))}
        {selected?.next_run_at && (
          <Tooltip title={formatAbsoluteTime(selected.next_run_at)}>
            <Typography component="span" variant="body2" color="text.secondary">
              {` · next run ${formatRelativeTime(selected.next_run_at)}`}
            </Typography>
          </Tooltip>
        )}
        {extra > 0 && (
          <Typography component="span" variant="body2" color="text.secondary">
            {` (+${extra} more)`}
          </Typography>
        )}
      </Typography>
    );
  }

  return (
    <Stack
      direction="row"
      spacing={1}
      alignItems="center"
      data-testid="inv-schedule-summary"
      sx={{ minWidth: 0 }}
    >
      <ScheduleIcon fontSize="small" color="action" />
      {content}
    </Stack>
  );
}
