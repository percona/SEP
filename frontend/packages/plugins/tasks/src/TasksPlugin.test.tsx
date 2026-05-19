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
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { TasksPlugin } from './TasksPlugin';

describe('TasksPlugin', () => {
  it('renders the list shell at the index route', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <TasksPlugin />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Task Manager' })).toBeInTheDocument();
    expect(screen.getByText(/legacy \/tasks\/ page/i)).toBeInTheDocument();
  });

  it('renders the detail shell for a task route', () => {
    render(
      <MemoryRouter initialEntries={['/my-task']}>
        <TasksPlugin />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'my-task' })).toBeInTheDocument();
    expect(screen.getByText(/task detail view \(shell\)/i)).toBeInTheDocument();
  });
});
