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

import { STORED_FORM_KEY } from '@sep/framework';
import { describe, expect, it } from 'vitest';
import { getAltersExecuteActions, getAltersHistoryTaskNames } from './altersTaskDetail';

describe('getAltersHistoryTaskNames', () => {
  it('returns parent, pre-checks, and dry-run task names', () => {
    expect(getAltersHistoryTaskNames({ name: 'my-alter' })).toEqual([
      'my-alter',
      'my-alter-pre-checks',
      'my-alter-dry-run',
    ]);
  });

  it('returns an empty list when the parent name is missing', () => {
    expect(getAltersHistoryTaskNames({})).toEqual([]);
    expect(getAltersHistoryTaskNames({ name: '   ' })).toEqual([]);
  });
});

describe('getAltersExecuteActions', () => {
  it('wires pre-checks execute with chain fields from stored form', () => {
    const task = {
      name: 'my-alter',
      data: {
        [STORED_FORM_KEY]: {
          continue_on_pre_check_failure: true,
        },
      },
    };

    const actions = getAltersExecuteActions(task);

    expect(actions).toHaveLength(3);
    expect(actions[0]).toMatchObject({
      label: 'Pre-checks',
      taskName: 'my-alter-pre-checks',
      testId: 'alters-pre-checks-execute',
      executeBody: {
        chain_task_names: ['my-alter'],
        chain_on_failure: true,
      },
    });
    expect(actions[1]).toMatchObject({
      label: 'Dry run',
      taskName: 'my-alter-dry-run',
      testId: 'alters-dry-run-execute',
    });
    expect(actions[1]).not.toHaveProperty('executeBody');
    expect(actions[2]).toMatchObject({
      label: 'Execute',
      taskName: 'my-alter',
      testId: 'alters-execute',
    });
    expect(actions[2]).not.toHaveProperty('executeBody');
  });

  it('defaults chain_on_failure to false when the stored form omits it', () => {
    const actions = getAltersExecuteActions({ name: 'my-alter' });

    expect(actions[0]?.executeBody).toEqual({
      chain_task_names: ['my-alter'],
      chain_on_failure: false,
    });
  });

  it('returns no actions when the parent name is missing', () => {
    expect(getAltersExecuteActions({})).toEqual([]);
  });
});
