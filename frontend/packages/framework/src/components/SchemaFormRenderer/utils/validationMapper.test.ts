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
import type { AppField } from '../types';
import { coerceFormValues } from './validationMapper';

const multiServiceField: AppField = {
  type: 'multi_service',
  name: 'services',
  label: 'Services',
  service_types: ['mysql'],
};

describe('coerceFormValues — multi reference fields', () => {
  it('normalizes an untouched empty-string multi field to an empty array', () => {
    // An optional multi field seeds as '' when left untouched; it must submit [].
    expect(coerceFormValues({ services: '' }, [multiServiceField])).toEqual({ services: [] });
    expect(coerceFormValues({ services: null }, [multiServiceField])).toEqual({ services: [] });
  });

  it('normalizes option objects to ids and drops empty entries in a multi array', () => {
    expect(
      coerceFormValues({ services: [{ id: 10, name: 'a' }, 5, '', 'custom'] }, [multiServiceField]),
    ).toEqual({ services: [10, 5, 'custom'] });
  });
});
