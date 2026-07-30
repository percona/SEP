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

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';

import AppDisabledPage from './AppDisabledPage';

describe('AppDisabledPage', () => {
  it('shows the generic disabled-app copy', () => {
    render(
      <MemoryRouter>
        <AppDisabledPage />
      </MemoryRouter>,
    );
    expect(screen.getByText('This feature is currently disabled.')).toBeInTheDocument();
    expect(screen.getByText('Contact an administrator to re-enable it.')).toBeInTheDocument();
  });

  it('names the blocking required app when a single dependency is off', () => {
    render(
      <MemoryRouter>
        <AppDisabledPage
          appDisplayName="Collect Diagnostic Data"
          blockingDependencyNames={['Snippet Manager']}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('Collect Diagnostic Data is unavailable')).toBeInTheDocument();
    expect(
      screen.getByText(
        'The Snippet Manager app must be enabled first. Contact an administrator to enable it.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('Contact an administrator to re-enable it.')).not.toBeInTheDocument();
  });

  it('names every blocking app when several dependencies are off', () => {
    render(
      <MemoryRouter>
        <AppDisabledPage
          appDisplayName="Collect Diagnostic Data"
          blockingDependencyNames={['Snippet Manager', 'Task Manager']}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('Collect Diagnostic Data is unavailable')).toBeInTheDocument();
    expect(
      screen.getByText(
        'These apps must be enabled first: Snippet Manager, Task Manager. Contact an administrator to enable them.',
      ),
    ).toBeInTheDocument();
  });

  it('falls back to "This feature" in the title when the app name is absent', () => {
    render(
      <MemoryRouter>
        <AppDisabledPage blockingDependencyNames={['Snippet Manager']} />
      </MemoryRouter>,
    );
    expect(screen.getByText('This feature is unavailable')).toBeInTheDocument();
    expect(
      screen.getByText(
        'The Snippet Manager app must be enabled first. Contact an administrator to enable it.',
      ),
    ).toBeInTheDocument();
  });

  it('names every blocking app in the body when the app name is absent', () => {
    render(
      <MemoryRouter>
        <AppDisabledPage blockingDependencyNames={['Snippet Manager', 'Task Manager']} />
      </MemoryRouter>,
    );
    expect(screen.getByText('This feature is unavailable')).toBeInTheDocument();
    expect(
      screen.getByText(
        'These apps must be enabled first: Snippet Manager, Task Manager. Contact an administrator to enable them.',
      ),
    ).toBeInTheDocument();
  });

  it('shows the generic copy when no blocking dependency is supplied', () => {
    render(
      <MemoryRouter>
        <AppDisabledPage appDisplayName="Collect Diagnostic Data" blockingDependencyNames={[]} />
      </MemoryRouter>,
    );
    expect(screen.getByText('This feature is currently disabled.')).toBeInTheDocument();
    expect(screen.getByText('Contact an administrator to re-enable it.')).toBeInTheDocument();
  });

  it('navigates to the dashboard when "Back to Dashboard" is clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/snippets']}>
        <Routes>
          <Route path="/" element={<div>dashboard root</div>} />
          <Route path="/snippets" element={<AppDisabledPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByText('dashboard root')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Back to Dashboard' }));
    expect(screen.getByText('dashboard root')).toBeInTheDocument();
  });
});
