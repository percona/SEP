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

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { SchemaFormRenderer } from './SchemaFormRenderer';
import { buildValidationRules, coerceFormValues } from './utils/validationMapper';
import { evaluatePredicate } from './utils/predicateEvaluator';
import type { FormSection } from './types';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
import { apiClient } from '@sep/api';
const mockedApi = apiClient as unknown as { get: ReturnType<typeof vi.fn> };

function renderWithProviders(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe('buildValidationRules', () => {
  it('emits required + minLength + maxLength + pattern for string fields', () => {
    const rules = buildValidationRules({
      type: 'string',
      name: 'title',
      label: 'Title',
      required: true,
      min_length: 3,
      max_length: 10,
      pattern: '^[a-z]+$',
    });
    expect(rules.required).toBe('Title is required');
    expect(rules.minLength).toMatchObject({ value: 3 });
    expect(rules.maxLength).toMatchObject({ value: 10 });
    expect((rules.pattern as { value: RegExp }).value).toBeInstanceOf(RegExp);
  });

  it('emits min/max for integer ge/le', () => {
    const rules = buildValidationRules({
      type: 'integer',
      name: 'n',
      label: 'N',
      ge: 1,
      le: 5,
    });
    expect(rules.min).toMatchObject({ value: 1 });
    expect(rules.max).toMatchObject({ value: 5 });
  });

  it('emits a validate fn enforcing minItems/maxItems on multichoice', () => {
    const rules = buildValidationRules({
      type: 'multichoice',
      name: 'tags',
      label: 'Tags',
      choices: [{ label: 'A', value: 'a' }],
      min_items: 1,
      max_items: 2,
    });
    const validate = rules.validate as (value: unknown) => true | string;
    expect(validate([])).toMatch(/at least 1/);
    expect(validate(['a'])).toBe(true);
    expect(validate(['a', 'b', 'c'])).toMatch(/at most 2/);
  });
});

describe('coerceFormValues', () => {
  it('parses integer strings and coerces empty to undefined', () => {
    const out = coerceFormValues({ age: '42', weight: '3.14', empty: '' }, [
      { type: 'integer', name: 'age', label: 'Age' },
      { type: 'float', name: 'weight', label: 'Weight' },
      { type: 'integer', name: 'empty', label: 'Empty' },
    ]);
    expect(out.age).toBe(42);
    expect(out.weight).toBeCloseTo(3.14);
    expect(out.empty).toBeUndefined();
  });

  it('leaves non-numeric fields alone', () => {
    const out = coerceFormValues({ title: 'hi', flag: true }, [
      { type: 'string', name: 'title', label: 'Title' },
      { type: 'bool', name: 'flag', label: 'Flag' },
    ]);
    expect(out).toEqual({ title: 'hi', flag: true });
  });

  it('unwraps option objects from service/schema/table/host fields to scalar ids', () => {
    const out = coerceFormValues(
      {
        serviceId: { id: 7, name: 'svc', type: 'mysql' },
        schemaName: { id: 11, name: 'app_prod' },
        tbl: { id: 101, name: 'users' },
        hostId: { id: 'nomad-1', name: 'db-mysql-01', address: '10.0.0.1' },
        empty: '',
      },
      [
        { type: 'service', name: 'serviceId', label: 'Service', service_types: [] },
        { type: 'schema', name: 'schemaName', label: 'Schema', depends_on: 'serviceId' },
        { type: 'table', name: 'tbl', label: 'Table', depends_on: 'schemaName' },
        { type: 'host', name: 'hostId', label: 'Host' },
        { type: 'service', name: 'empty', label: 'Empty', service_types: [] },
      ],
    );
    expect(out.serviceId).toBe(7);
    expect(out.schemaName).toBe(11);
    expect(out.tbl).toBe(101);
    expect(out.hostId).toBe('nomad-1');
    expect(out.empty).toBeUndefined();
  });
});

describe('SchemaFormRenderer — field rendering', () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
    mockedApi.get.mockResolvedValue({ data: [] });
  });

  const sections: FormSection[] = [
    {
      title: 'Basics',
      fields: [
        { type: 'string', name: 'title', label: 'Title', required: true, min_length: 3 },
        { type: 'integer', name: 'count', label: 'Count', ge: 1, le: 10 },
        { type: 'float', name: 'rate', label: 'Rate', ge: 0, le: 1, step: 0.01 },
        { type: 'bool', name: 'active', label: 'Active' },
        {
          type: 'choice',
          name: 'size',
          label: 'Size',
          choices: [
            { label: 'Small', value: 's' },
            { label: 'Medium', value: 'm' },
            { label: 'Large', value: 'l' },
            { label: 'Extra', value: 'xl' },
          ],
        },
        {
          type: 'multichoice',
          name: 'tags',
          label: 'Tags',
          choices: [
            { label: 'Alpha', value: 'a' },
            { label: 'Beta', value: 'b' },
          ],
        },
        { type: 'textarea', name: 'notes', label: 'Notes' },
        { type: 'datetime', name: 'when', label: 'When' },
        { type: 'yaml', name: 'cfg', label: 'Config' },
        { type: 'file', name: 'upload', label: 'Upload' },
        { type: 'table', name: 'tbl', label: 'Table', depends_on: 'schemaName' },
        { type: 'host', name: 'hostId', label: 'Host' },
      ],
    },
  ];

  it('renders every declared field', () => {
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);
    expect(screen.getByLabelText(/Title/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Count/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Rate/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Active/)).toBeInTheDocument();
    // percona-ui's SelectInput does not expose the label as accessible name;
    // identify by the stable MUI-generated id instead.
    expect(document.getElementById('mui-component-select-size')).not.toBeNull();
    expect(document.getElementById('mui-component-select-tags')).not.toBeNull();
    expect(screen.getByLabelText(/Notes/)).toBeInTheDocument();
    expect(screen.getByLabelText(/When/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Config/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Upload/)).toBeInTheDocument();
    // ServiceSelector / SchemaSelector / TableSelector / HostSelector use
    // percona-ui's AutoCompleteInput which renders a TextField — assert by label.
    expect(screen.getByLabelText('Table')).toBeInTheDocument();
    expect(screen.getByLabelText('Host')).toBeInTheDocument();
  });

  it('groups fields under section titles as fieldset legends', () => {
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);
    const legend = screen.getByText('Basics');
    expect(legend.tagName.toLowerCase()).toBe('legend');
  });
});

describe('SchemaFormRenderer — validation + submission', () => {
  it('blocks submission when a required field is empty and surfaces global banner', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const sections: FormSection[] = [
      {
        title: 'Main',
        fields: [{ type: 'string', name: 'title', label: 'Title', required: true }],
      },
    ];
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    await user.click(screen.getByRole('button', { name: /Run/ }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/Fix the highlighted fields/)).toBeInTheDocument();
    expect(screen.getByText(/Title is required/)).toBeInTheDocument();
  });

  it('submits coerced numeric values on valid input', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const sections: FormSection[] = [
      {
        title: 'Main',
        fields: [
          { type: 'string', name: 'title', label: 'Title', required: true },
          { type: 'integer', name: 'count', label: 'Count' },
        ],
      },
    ];
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText(/Title/), 'hello');
    await user.type(screen.getByLabelText(/Count/), '7');
    await user.click(screen.getByRole('button', { name: /Run/ }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ title: 'hello', count: 7 }));
  });

  it('renders the server submitError banner when provided', () => {
    renderWithProviders(
      <SchemaFormRenderer
        sections={[{ title: 'x', fields: [{ type: 'string', name: 'a', label: 'A' }] }]}
        onSubmit={() => {}}
        submitError="Server exploded"
      />,
    );
    expect(screen.getByText('Server exploded')).toBeInTheDocument();
  });
});

describe('SchemaFormRenderer — multichoice minItems', () => {
  it('blocks submission when selection count is below minItems', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const sections: FormSection[] = [
      {
        title: 'Main',
        fields: [
          {
            type: 'multichoice',
            name: 'tags',
            label: 'Tags',
            choices: [
              { label: 'Alpha', value: 'a' },
              { label: 'Beta', value: 'b' },
            ],
            min_items: 1,
          },
        ],
      },
    ];
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    await user.click(screen.getByRole('button', { name: /Run/ }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/Fix the highlighted fields/)).toBeInTheDocument();
    // percona-ui's SelectInput does not render the validate message visibly,
    // but it does flip aria-invalid on the native input — use that as the
    // end-to-end proof that the minItems validate fn ran and blocked submit.
    await waitFor(() =>
      expect(screen.getByTestId('select-input-tags')).toHaveAttribute('aria-invalid', 'true'),
    );
  });
});

describe('SchemaFormRenderer — file required', () => {
  it('blocks submission when a required file field is empty', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const sections: FormSection[] = [
      {
        title: 'Main',
        fields: [{ type: 'file', name: 'upload', label: 'Upload', required: true }],
      },
    ];
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    await user.click(screen.getByRole('button', { name: /Run/ }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/Fix the highlighted fields/)).toBeInTheDocument();
    expect(screen.getByText(/Upload is required/)).toBeInTheDocument();
  });
});

describe('SchemaFormRenderer — cascade behaviour', () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
  });

  it('clears downstream schema value when the upstream service changes', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/inventory/services/') {
        return Promise.resolve({
          data: {
            items: [
              { id: 1, name: 'mysql-prod-1', type: 'mysql' },
              { id: 2, name: 'mysql-staging-1', type: 'mysql' },
            ],
            total: 2,
            offset: 0,
            limit: 200,
          },
        });
      }
      if (url === '/inventory-api/services/1/schemas') {
        return Promise.resolve({ data: [{ id: 11, name: 'app_production' }] });
      }
      if (url === '/inventory-api/services/2/schemas') {
        return Promise.resolve({ data: [{ id: 21, name: 'app_staging' }] });
      }
      return Promise.resolve({ data: [] });
    });

    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const sections: FormSection[] = [
      {
        title: 'Target',
        fields: [
          {
            type: 'service',
            name: 'serviceId',
            label: 'Service',
            service_types: ['mysql'],
          },
          { type: 'schema', name: 'schemaName', label: 'Schema', depends_on: 'serviceId' },
        ],
      },
    ];
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    const serviceCombo = screen.getByLabelText('Service');
    const schemaCombo = screen.getByLabelText('Schema');

    // Wait for services to load.
    await waitFor(() =>
      expect(mockedApi.get).toHaveBeenCalledWith('/inventory/services/', expect.anything()),
    );

    // Pick first service.
    await user.click(serviceCombo);
    const svcOption = await screen.findByRole('option', { name: /mysql-prod-1/ });
    await user.click(svcOption);

    // Schema fetch fires, dropdown becomes enabled.
    await waitFor(() => expect(schemaCombo).not.toBeDisabled());

    await user.click(schemaCombo);
    const schemaOption = await screen.findByRole('option', { name: 'app_production' });
    await user.click(schemaOption);
    expect((schemaCombo as HTMLInputElement).value).toBe('app_production');

    // Switch to another service — schema should be cleared by the cascade reset.
    await user.click(serviceCombo);
    const svc2 = await screen.findByRole('option', { name: /mysql-staging-1/ });
    await user.click(svc2);

    await waitFor(() => {
      expect((schemaCombo as HTMLInputElement).value).toBe('');
    });
  });
});

// ── evaluatePredicate ──────────────────────────────────────────────────────

describe('evaluatePredicate', () => {
  const v = (overrides: Record<string, unknown>) => overrides;

  it('truthy / falsy', () => {
    expect(evaluatePredicate({ truthy: 'x' }, v({ x: 'yes' }))).toBe(true);
    expect(evaluatePredicate({ truthy: 'x' }, v({ x: '' }))).toBe(false);
    expect(evaluatePredicate({ falsy: 'x' }, v({ x: '' }))).toBe(true);
    expect(evaluatePredicate({ falsy: 'x' }, v({ x: 1 }))).toBe(false);
    expect(evaluatePredicate({ truthy: 'arr' }, v({ arr: ['a'] }))).toBe(true);
    expect(evaluatePredicate({ truthy: 'arr' }, v({ arr: [] }))).toBe(false);
    // empty plain objects are falsy — mirrors Python bool({}) = False
    expect(evaluatePredicate({ truthy: 'obj' }, v({ obj: {} }))).toBe(false);
    expect(evaluatePredicate({ truthy: 'obj' }, v({ obj: { k: 1 } }))).toBe(true);
    expect(evaluatePredicate({ falsy: 'obj' }, v({ obj: {} }))).toBe(true);
  });

  it('equals / not_equals', () => {
    expect(evaluatePredicate({ equals: { mode: 'advanced' } }, v({ mode: 'advanced' }))).toBe(true);
    expect(evaluatePredicate({ equals: { mode: 'basic' } }, v({ mode: 'advanced' }))).toBe(false);
    expect(evaluatePredicate({ not_equals: { mode: 'basic' } }, v({ mode: 'advanced' }))).toBe(
      true,
    );
  });

  it('equals with $field ref', () => {
    expect(evaluatePredicate({ equals: { a: { $field: 'b' } } }, v({ a: 'x', b: 'x' }))).toBe(true);
    expect(evaluatePredicate({ equals: { a: { $field: 'b' } } }, v({ a: 'x', b: 'y' }))).toBe(
      false,
    );
  });

  it('gt / gte / lt / lte', () => {
    expect(evaluatePredicate({ gt: { n: 5 } }, v({ n: 6 }))).toBe(true);
    expect(evaluatePredicate({ gt: { n: 5 } }, v({ n: 5 }))).toBe(false);
    expect(evaluatePredicate({ gte: { n: 5 } }, v({ n: 5 }))).toBe(true);
    expect(evaluatePredicate({ lt: { n: 5 } }, v({ n: 4 }))).toBe(true);
    expect(evaluatePredicate({ lte: { n: 5 } }, v({ n: 5 }))).toBe(true);
    // RHF stores text-input values as strings — coerce before comparing
    expect(evaluatePredicate({ gt: { n: 5 } }, v({ n: '6' }))).toBe(true);
    expect(evaluatePredicate({ gt: { n: 5 } }, v({ n: '10' }))).toBe(true); // would be false lexicographically
    expect(evaluatePredicate({ lt: { n: 10 } }, v({ n: '9' }))).toBe(true); // "9" < "10" is false lexicographically
  });

  it('gt / gte / lt / lte with $field ref', () => {
    expect(evaluatePredicate({ gt: { a: { $field: 'b' } } }, v({ a: 6, b: 5 }))).toBe(true);
    expect(evaluatePredicate({ gt: { a: { $field: 'b' } } }, v({ a: 5, b: 5 }))).toBe(false);
    expect(evaluatePredicate({ gte: { a: { $field: 'b' } } }, v({ a: 5, b: 5 }))).toBe(true);
    expect(evaluatePredicate({ lt: { a: { $field: 'b' } } }, v({ a: 4, b: 5 }))).toBe(true);
    expect(evaluatePredicate({ lte: { a: { $field: 'b' } } }, v({ a: 5, b: 5 }))).toBe(true);
  });

  it('any_present / all_present / none_present', () => {
    expect(evaluatePredicate({ any_present: ['a', 'b'] }, v({ a: '', b: 'x' }))).toBe(true);
    expect(evaluatePredicate({ any_present: ['a', 'b'] }, v({ a: '', b: '' }))).toBe(false);
    expect(evaluatePredicate({ all_present: ['a', 'b'] }, v({ a: '1', b: '2' }))).toBe(true);
    expect(evaluatePredicate({ all_present: ['a', 'b'] }, v({ a: '1', b: '' }))).toBe(false);
    expect(evaluatePredicate({ none_present: ['a', 'b'] }, v({ a: '', b: '' }))).toBe(true);
    expect(evaluatePredicate({ none_present: ['a', 'b'] }, v({ a: 'x', b: '' }))).toBe(false);
    // empty arrays are absent (mirrors BE behaviour for multiselect/list fields)
    expect(evaluatePredicate({ any_present: ['tags'] }, v({ tags: [] }))).toBe(false);
    expect(evaluatePredicate({ all_present: ['tags'] }, v({ tags: [] }))).toBe(false);
    expect(evaluatePredicate({ none_present: ['tags'] }, v({ tags: [] }))).toBe(true);
    expect(evaluatePredicate({ any_present: ['tags'] }, v({ tags: ['x'] }))).toBe(true);
    // empty plain objects are absent — mirrors BE _field_is_present({}) = False
    expect(evaluatePredicate({ any_present: ['obj'] }, v({ obj: {} }))).toBe(false);
    expect(evaluatePredicate({ any_present: ['obj'] }, v({ obj: { k: 1 } }))).toBe(true);
    // empty operand list → false (no vacuous truth)
    expect(evaluatePredicate({ all_present: [] }, v({}))).toBe(false);
    expect(evaluatePredicate({ none_present: [] }, v({}))).toBe(false);
  });

  it('all_truthy / any_truthy / all_falsy / any_falsy', () => {
    expect(evaluatePredicate({ all_truthy: ['a', 'b'] }, v({ a: 1, b: 2 }))).toBe(true);
    expect(evaluatePredicate({ all_truthy: ['a', 'b'] }, v({ a: 1, b: 0 }))).toBe(false);
    expect(evaluatePredicate({ any_truthy: ['a', 'b'] }, v({ a: 0, b: 1 }))).toBe(true);
    expect(evaluatePredicate({ all_falsy: ['a', 'b'] }, v({ a: 0, b: '' }))).toBe(true);
    expect(evaluatePredicate({ any_falsy: ['a', 'b'] }, v({ a: 1, b: 0 }))).toBe(true);
    // empty operand list → false (no vacuous truth)
    expect(evaluatePredicate({ all_truthy: [] }, v({}))).toBe(false);
    expect(evaluatePredicate({ all_falsy: [] }, v({}))).toBe(false);
  });

  it('all_equal', () => {
    expect(evaluatePredicate({ all_equal: ['a', 'b', 'c'] }, v({ a: 'x', b: 'x', c: 'x' }))).toBe(
      true,
    );
    expect(evaluatePredicate({ all_equal: ['a', 'b'] }, v({ a: 'x', b: 'y' }))).toBe(false);
    // requires at least 2 fields — fewer returns false
    expect(evaluatePredicate({ all_equal: [] }, v({}))).toBe(false);
    expect(evaluatePredicate({ all_equal: ['a'] }, v({ a: 'x' }))).toBe(false);
  });

  it('all / any (logical combinators)', () => {
    expect(evaluatePredicate({ all: [{ truthy: 'a' }, { truthy: 'b' }] }, v({ a: 1, b: 1 }))).toBe(
      true,
    );
    expect(evaluatePredicate({ all: [{ truthy: 'a' }, { truthy: 'b' }] }, v({ a: 1, b: 0 }))).toBe(
      false,
    );
    expect(evaluatePredicate({ any: [{ truthy: 'a' }, { truthy: 'b' }] }, v({ a: 0, b: 1 }))).toBe(
      true,
    );
    // empty all combinator → false (no vacuous truth)
    expect(evaluatePredicate({ all: [] }, v({}))).toBe(false);
  });

  it('xor — binary and n-ary (exactly one truthy)', () => {
    // binary cases
    expect(evaluatePredicate({ xor: [{ truthy: 'a' }, { truthy: 'b' }] }, v({ a: 1, b: 0 }))).toBe(
      true,
    );
    expect(evaluatePredicate({ xor: [{ truthy: 'a' }, { truthy: 'b' }] }, v({ a: 1, b: 1 }))).toBe(
      false,
    );
    expect(evaluatePredicate({ xor: [{ truthy: 'a' }, { truthy: 'b' }] }, v({ a: 0, b: 0 }))).toBe(
      false,
    );
    // n-ary: exactly one of three
    expect(
      evaluatePredicate(
        { xor: [{ truthy: 'a' }, { truthy: 'b' }, { truthy: 'c' }] },
        v({ a: 1, b: 0, c: 0 }),
      ),
    ).toBe(true);
    expect(
      evaluatePredicate(
        { xor: [{ truthy: 'a' }, { truthy: 'b' }, { truthy: 'c' }] },
        v({ a: 1, b: 1, c: 0 }),
      ),
    ).toBe(false);
    // empty → false
    expect(evaluatePredicate({ xor: [] }, v({}))).toBe(false);
  });

  it('not', () => {
    expect(evaluatePredicate({ not: { truthy: 'x' } }, v({ x: '' }))).toBe(true);
    expect(evaluatePredicate({ not: { truthy: 'x' } }, v({ x: 'yes' }))).toBe(false);
  });

  it('returns false for unknown operator', () => {
    expect(evaluatePredicate({ unknown_op: 'x' } as Record<string, unknown>, v({}))).toBe(false);
  });
});

// ── Conditional visibility (forbidden gates) ───────────────────────────────

describe('SchemaFormRenderer — conditional visibility', () => {
  const sections: FormSection[] = [
    {
      title: 'Main',
      fields: [
        { type: 'bool', name: 'advanced', label: 'Advanced mode' },
        {
          type: 'string',
          name: 'advancedOption',
          label: 'Advanced option',
          forbidden: [{ when: { falsy: 'advanced' } }],
        },
      ],
    },
  ];

  it('hides a field when its forbidden gate fires', () => {
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);
    // advanced = false (default) → forbidden gate fires → advancedOption hidden
    expect(screen.queryByLabelText('Advanced option')).toBeNull();
  });

  it('shows a field when its forbidden gate no longer fires', async () => {
    const user = userEvent.setup();
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);

    // Flip the bool — advanced becomes true → falsy('advanced') = false → gate doesn't fire
    await user.click(screen.getByLabelText('Advanced mode'));
    expect(await screen.findByLabelText('Advanced option')).toBeInTheDocument();
  });

  it('excludes hidden field from submission', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    // advanced=false → advancedOption hidden → submit without it
    await user.click(screen.getByRole('button', { name: /Run/ }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.not.objectContaining({ advancedOption: expect.anything() }),
    );
  });

  it('includes revealed field in submission', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    await user.click(screen.getByLabelText('Advanced mode'));
    const input = await screen.findByLabelText('Advanced option');
    await user.type(input, 'secret');
    await user.click(screen.getByRole('button', { name: /Run/ }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ advancedOption: 'secret' }));
  });
});

// ── Conditional required (requires gates) ─────────────────────────────────

describe('SchemaFormRenderer — conditional required', () => {
  const sections: FormSection[] = [
    {
      title: 'Main',
      fields: [
        { type: 'bool', name: 'needsReason', label: 'Needs reason' },
        {
          type: 'string',
          name: 'reason',
          label: 'Reason',
          requires: [{ when: { truthy: 'needsReason' } }],
        },
      ],
    },
  ];

  it('does not block submission when gate is inactive', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    // needsReason=false → requires gate inactive → reason not required
    await user.click(screen.getByRole('button', { name: /Run/ }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it('blocks submission and shows required error when gate fires and field is empty', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    await user.click(screen.getByLabelText('Needs reason'));
    await user.click(screen.getByRole('button', { name: /Run/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/Reason is required/)).toBeInTheDocument();
  });

  it('submits when gate fires and field is filled', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    await user.click(screen.getByLabelText('Needs reason'));
    // Use data-testid (set by percona-ui's TextInput) to find the input directly,
    // since the label-for association is briefly stale while isRequired flips.
    await user.type(screen.getByTestId('text-input-reason'), 'because');
    await user.click(screen.getByRole('button', { name: /Run/ }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'because', needsReason: true }),
    );
  });
});
