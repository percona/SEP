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

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LastRunStatus } from './LastRunStatus';
import type { PeriodicTaskResponse } from './hooks';

type Status = PeriodicTaskResponse['last_run_status'];

describe('LastRunStatus', () => {
  it('renders the shared status badge for a recognized outcome', () => {
    render(<LastRunStatus status="success" lastRunAt="2026-06-18T10:00:00Z" />);

    const badge = document.querySelector('[data-status="success"]');
    expect(badge).not.toBeNull();
    expect(badge).toHaveTextContent('Done');
  });

  it('maps every recognized status to a badge rather than an empty state', () => {
    const statuses: Status[] = [
      'success',
      'failed',
      'running',
      'pending',
      'stopped',
      'lost',
      'stale',
      'unlaunchable',
    ];
    for (const status of statuses) {
      const { unmount } = render(
        <LastRunStatus status={status} lastRunAt="2026-06-18T10:00:00Z" />,
      );
      expect(document.querySelector(`[data-status="${status}"]`)).not.toBeNull();
      expect(screen.queryByTestId('last-run-never')).not.toBeInTheDocument();
      unmount();
    }
  });

  it('shows "Not yet run" only when the schedule has genuinely never run', () => {
    render(<LastRunStatus status={null} lastRunAt={null} />);

    expect(screen.getByTestId('last-run-never')).toHaveTextContent('Not yet run');
    expect(document.querySelector('[data-status]')).toBeNull();
  });

  it('shows "Unknown", not "Not yet run", when the task ran but no result resolved', () => {
    render(<LastRunStatus status={null} lastRunAt="2026-06-18T10:00:00Z" />);

    expect(screen.getByTestId('last-run-unknown')).toHaveTextContent('Unknown');
    expect(screen.queryByTestId('last-run-never')).not.toBeInTheDocument();
  });

  it('treats an undefined status like an absent one', () => {
    render(<LastRunStatus status={undefined} lastRunAt={null} />);

    expect(screen.getByTestId('last-run-never')).toHaveTextContent('Not yet run');
  });

  it('renders an unrecognized-but-present status verbatim instead of dropping it', () => {
    // The typed API only emits known enum values, but a runtime value the
    // frontend enum has not caught up to must still surface rather than be
    // silently folded into "Not yet run".
    render(<LastRunStatus status={'queued' as Status} lastRunAt="2026-06-18T10:00:00Z" />);

    expect(screen.getByTestId('last-run-unrecognized')).toHaveTextContent('queued');
    expect(screen.queryByTestId('last-run-never')).not.toBeInTheDocument();
  });
});
