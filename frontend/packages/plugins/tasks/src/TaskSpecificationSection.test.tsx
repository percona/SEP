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

import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TaskSpecificationSection } from './TaskSpecificationSection';

vi.mock('@sep/framework', () => ({
  detailSyntaxBlockSx: {},
  DetailSyntaxHighlighter: ({ value }: { value: unknown }) => (
    <pre data-testid="detail-syntax-highlighter">{JSON.stringify(value, null, 2)}</pre>
  ),
}));

describe('TaskSpecificationSection', () => {
  it('renders an expanded accordion with syntax-highlighted task JSON', async () => {
    render(
      <TaskSpecificationSection
        task={{ name: 'monitor-task', backend: 'nomad', is_template: false }}
      />,
    );

    expect(screen.getByRole('button', { name: 'Specification' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );

    await waitFor(() => {
      expect(screen.getByTestId('detail-syntax-highlighter')).toHaveTextContent(
        '"name": "monitor-task"',
      );
    });
  });
});
