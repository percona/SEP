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

import type { TaskExecuteAction } from '@sep/framework';

/** Must stay in sync with ``alters_schema.derived[0].name_suffix``. */
const DRY_RUN_SUFFIX = '-dry-run';

/** Must stay in sync with ``alters_schema.predecessors[0].name_suffix``. */
const PRE_CHECKS_SUFFIX = '-pre-checks';

function readParentTaskName(task: Record<string, unknown>): string {
  return typeof task.name === 'string' ? task.name.trim() : '';
}

function altersGroupTaskNames(parentName: string): string[] {
  if (!parentName) {
    return [];
  }
  return [parentName, `${parentName}${PRE_CHECKS_SUFFIX}`, `${parentName}${DRY_RUN_SUFFIX}`];
}

/** Include parent, pre-checks, and dry-run histories on the Logs tab. */
export function getAltersHistoryTaskNames(task: Record<string, unknown>): string[] {
  return altersGroupTaskNames(readParentTaskName(task));
}

/** Replace the default single Execute button with the three-task group actions. */
export function getAltersExecuteActions(task: Record<string, unknown>): TaskExecuteAction[] {
  const parentName = readParentTaskName(task);
  if (!parentName) {
    return [];
  }

  const preChecksName = `${parentName}${PRE_CHECKS_SUFFIX}`;
  const dryRunName = `${parentName}${DRY_RUN_SUFFIX}`;

  return [
    {
      label: 'Pre-checks',
      taskName: preChecksName,
      testId: 'alters-pre-checks-execute',
      confirmMessage: `Run pre-checks for "${parentName}" now?`,
    },
    {
      label: 'Dry run',
      taskName: dryRunName,
      testId: 'alters-dry-run-execute',
      confirmMessage: `Run pt-online-schema-change in dry-run mode for "${parentName}"?`,
    },
    {
      label: 'Execute',
      taskName: parentName,
      testId: 'alters-execute',
      confirmMessage: `Execute the schema change for "${parentName}" now?`,
    },
  ];
}
