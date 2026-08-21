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

import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Every mutation in SEP can be refused — the API restricts state-changing
 * routes to admins — so a call site that fires one and reports nothing leaves
 * the user with silence instead of a reason. Nine such sites existed before
 * this guard, all of them omissions rather than mistakes, which is why the
 * omission is caught here rather than in review.
 *
 * A file that calls ``.mutate`` / ``.mutateAsync`` passes by using the shared
 * primitive (``ActionErrorAlert`` / ``useActionError`` / ``actionErrorMessage``)
 * or the form path (``mapSubmitError``), or by being listed in
 * {@link REPORTS_ITS_OWN_WAY} with the mechanism it uses instead.
 *
 * A new call site therefore has exactly two ways forward: adopt the primitive,
 * or state in the allowlist how the failure reaches the user. Adding nothing
 * fails this test.
 *
 * Granularity is the file, not the individual call: a file that already reports
 * one action's failures passes even if a second mutation is added to it unwired.
 * Tightening that would mean parsing each call's surroundings, which trades a
 * mechanical check for a heuristic one; the omissions this guard exists to catch
 * were whole files with no failure path at all.
 */
const PACKAGES_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

const PRIMITIVE_MARKERS = [
  'ActionErrorAlert',
  'useActionError',
  'actionErrorMessage',
  'mapSubmitError',
  // The JSX prop a caller owning a stop mutation passes to TaskHistoryTable, so
  // its failure renders above the rows the action was fired from. Matched with
  // the `={` so a same-named local `actionError` state cannot satisfy the guard
  // by accident.
  'actionError={',
];

/**
 * Call sites that already rendered a failure from SEP's own component tree
 * before the primitive existed, each with the mechanism it uses. They are
 * correct as they stand; migrating them onto the primitive can happen
 * opportunistically. Every entry must name where the message is rendered.
 */
const REPORTS_ITS_OWN_WAY: Record<string, string> = {
  'framework/src/components/ScheduledTasksPanel/ScheduledTasksPanel.tsx':
    'panel-level actionError / formError state rendered as an alert above the table',
  'framework/src/components/TaskHistoryTable/TaskFilesDialog.tsx':
    'in-dialog alert reading the download mutation error',
  'shell/src/components/settings/SettingRow.tsx':
    'per-field error text from settingErrorMessage plus a row-level message',
  'shell/src/components/settings/TestConnectionButton.tsx':
    'inline alert reading the connectivity-check mutation error',
  'shell/src/pages/SettingsPage.tsx': 'page-level alert',
  'shell/src/pages/AdminAppsPage.tsx': 'page-level alert',
  'apps/snippets/src/SnippetDetailPage.tsx': 'inline alert reading the mutation error',
  'apps/topology/src/TopologyView.tsx': 'inline alert reading the mutation error',
  'apps/atw/src/hooks.ts':
    'exposes a combined `error` from the lifecycle mutations, rendered by IncidentListPage',
  'apps/atw/src/CollectPane.tsx': 'form-level submitError banner',
  'apps/atw/src/SendDialog.tsx': 'in-dialog alert reading the mutation error',
  'apps/atw/src/IncidentListPage.tsx': 'inline alert reading the incident-action error',
  'apps/alerts/src/AlertsWizard.tsx': 'wizard-level alert reading the mutation error',
  'apps/inventory/src/InventorySchedulePage.tsx': 'page-level actionError alert',
  'apps/report/src/ReportResultPage.tsx': 'inline alert reading the mutation error',
};

const MUTATION_CALL = /\.(mutate|mutateAsync)\s*\(/;

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    // `e2e` drives a browser rather than rendering these components, and
    // `node_modules` is not ours to police.
    if (entry === 'node_modules' || entry === 'dist' || entry === 'e2e') {
      continue;
    }
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, acc);
      continue;
    }
    if (!/\.tsx?$/.test(entry) || /\.(test|stories)\.tsx?$/.test(entry)) {
      continue;
    }
    acc.push(full);
  }
  return acc;
}

describe('mutation failure reporting', () => {
  it('every mutation call site reports its failures in-tree', () => {
    const unreported: string[] = [];
    const files = sourceFiles(PACKAGES_DIR);

    // A mis-resolved root would make the scan pass by finding nothing at all.
    expect(files.length).toBeGreaterThan(100);
    expect(
      files.some((file) => file.endsWith(path.join('framework', 'src', 'index.ts'))),
      `Scan rooted at ${PACKAGES_DIR} did not reach the framework package.`,
    ).toBe(true);

    for (const file of files) {
      const source = readFileSync(file, 'utf8');
      if (!MUTATION_CALL.test(source)) {
        continue;
      }
      const relative = path.relative(PACKAGES_DIR, file).split(path.sep).join('/');
      if (relative in REPORTS_ITS_OWN_WAY) {
        continue;
      }
      if (PRIMITIVE_MARKERS.some((marker) => source.includes(marker))) {
        continue;
      }
      unreported.push(relative);
    }

    expect(
      unreported,
      [
        'These files fire a mutation but render no failure from SEP’s own component tree.',
        'Either report the error with ActionErrorAlert / useActionError (or mapSubmitError in a',
        'form), or add the file to REPORTS_ITS_OWN_WAY naming where its message is rendered.',
        'A toast alone does not count: the PMM-embedded host is not guaranteed to mount a',
        'snackbar provider.',
      ].join(' '),
    ).toEqual([]);
  });

  it('the allowlist has no stale entries', () => {
    const stale = Object.keys(REPORTS_ITS_OWN_WAY).filter((relative) => {
      const full = path.join(PACKAGES_DIR, relative);
      try {
        return !MUTATION_CALL.test(readFileSync(full, 'utf8'));
      } catch {
        return true;
      }
    });

    expect(stale, 'Allowlisted files that no longer fire a mutation; drop them.').toEqual([]);
  });
});
