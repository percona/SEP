import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { SchemaFormRenderer } from './SchemaFormRenderer';
import { buildValidationRules, coerceFormValues } from './utils/validationMapper';
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
        { type: 'service', name: 'serviceId', label: 'Service', serviceTypes: [] },
        { type: 'schema', name: 'schemaName', label: 'Schema', dependsOn: 'serviceId' },
        { type: 'table', name: 'tbl', label: 'Table', dependsOn: 'schemaName' },
        { type: 'host', name: 'hostId', label: 'Host' },
        { type: 'service', name: 'empty', label: 'Empty', serviceTypes: [] },
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
        { type: 'string', name: 'title', label: 'Title', required: true, minLength: 3 },
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
        { type: 'table', name: 'tbl', label: 'Table', dependsOn: 'schemaName' },
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
            minItems: 1,
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
      if (url === '/api/inventory/services/') {
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
            serviceTypes: ['mysql'],
          },
          { type: 'schema', name: 'schemaName', label: 'Schema', dependsOn: 'serviceId' },
        ],
      },
    ];
    renderWithProviders(<SchemaFormRenderer sections={sections} onSubmit={onSubmit} />);

    const serviceCombo = screen.getByLabelText('Service');
    const schemaCombo = screen.getByLabelText('Schema');

    // Wait for services to load.
    await waitFor(() =>
      expect(mockedApi.get).toHaveBeenCalledWith('/api/inventory/services/', expect.anything()),
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
