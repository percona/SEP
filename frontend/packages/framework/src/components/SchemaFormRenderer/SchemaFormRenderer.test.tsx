import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { SchemaFormRenderer } from './SchemaFormRenderer';
import { buildValidationRules, coerceFormValues } from './utils/validationMapper';
import type { FormSection } from './types';

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
      minLength: 3,
      maxLength: 10,
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
      minItems: 1,
      maxItems: 2,
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
});

describe('SchemaFormRenderer — field rendering', () => {
  const sections: FormSection[] = [
    {
      title: 'Basics',
      fields: [
        { type: 'string', name: 'title', label: 'Title', required: true, minLength: 3 },
        { type: 'integer', name: 'count', label: 'Count', ge: 1, le: 10 },
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
        { type: 'textarea', name: 'notes', label: 'Notes' },
        { type: 'datetime', name: 'when', label: 'When' },
        { type: 'yaml', name: 'cfg', label: 'Config' },
      ],
    },
  ];

  it('renders every declared field', () => {
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={() => {}} />);
    expect(screen.getByLabelText(/Title/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Count/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Active/)).toBeInTheDocument();
    // percona-ui's SelectInput does not expose the label as accessible name;
    // identify by the stable MUI-generated id instead.
    expect(document.getElementById('mui-component-select-size')).not.toBeNull();
    expect(screen.getByLabelText(/Notes/)).toBeInTheDocument();
    expect(screen.getByLabelText(/When/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Config/)).toBeInTheDocument();
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

describe('SchemaFormRenderer — cascade behaviour', () => {
  it('clears downstream schema value when the upstream service changes', async () => {
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
            serviceTypes: ['mysql'],
          },
          { type: 'schema', name: 'schemaName', label: 'Schema', dependsOn: 'serviceId' },
        ],
      },
    ];
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    const serviceCombo = document.getElementById('mui-component-select-serviceId')!;
    const schemaCombo = document.getElementById('mui-component-select-schemaName')!;
    expect(serviceCombo).toBeInTheDocument();
    expect(schemaCombo).toBeInTheDocument();

    // Pick first service
    await user.click(serviceCombo);
    const svcOption = await screen.findByRole('option', { name: /mysql-prod-1/ });
    await user.click(svcOption);

    // Wait for the schema select to become enabled, then pick a schema tied to svc-1
    await waitFor(() => expect(schemaCombo).not.toHaveAttribute('aria-disabled', 'true'));
    await user.click(schemaCombo);
    const schemaOption = await screen.findByRole('option', { name: 'app_production' });
    await user.click(schemaOption);

    // Confirm the schema value is set
    await waitFor(() => expect(schemaCombo).toHaveTextContent('app_production'));

    // Switch to another service — schema should be cleared by the cascade hook
    await user.click(serviceCombo);
    const svc2 = await screen.findByRole('option', { name: /mysql-staging-1/ });
    await user.click(svc2);

    await waitFor(() => {
      expect(schemaCombo).not.toHaveTextContent('app_production');
    });
  });
});
