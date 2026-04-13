import type { PluginSchema } from '@sep/api';

/**
 * Checksums plugin schema — defines the form and list view for pt-table-checksum tasks.
 *
 * This is the ONLY plugin-specific configuration needed.
 * The SchemaDrivenPlugin component auto-generates list, create, and detail pages
 * entirely from this definition.
 *
 * In production, this schema will be served by the backend at
 * GET /api/plugins/checksums/schema — this mock is used for development.
 */
export const checksumsSchema: PluginSchema = {
  name: 'checksums',
  displayName: 'Checksums',
  description: 'Run pt-table-checksum to verify data consistency between MySQL replicas.',
  taskType: 'pt-table-checksum',

  forms: [
    {
      title: 'Target',
      description: 'Select the MySQL service to run checksums against.',
      fields: [
        {
          name: 'serviceId',
          label: 'MySQL Service',
          type: 'service',
          required: true,
          serviceTypes: ['mysql'],
        },
        {
          name: 'schema',
          label: 'Schema',
          type: 'string',
          placeholder: 'Leave empty for all schemas',
          description: 'Optionally filter to a specific database schema.',
        },
      ],
    },
    {
      title: 'Options',
      fields: [
        {
          name: 'chunkSize',
          label: 'Chunk Size',
          type: 'choice',
          default: '1000',
          choices: [
            { label: '1,000', value: '1000' },
            { label: '5,000', value: '5000' },
            { label: '10,000', value: '10000' },
            { label: '50,000', value: '50000' },
          ],
        },
        {
          name: 'replicateCheck',
          label: 'Replicate check (--replicate-check)',
          type: 'bool',
          default: true,
        },
        {
          name: 'checkInterval',
          label: 'Check interval (seconds)',
          type: 'integer',
          default: 1,
          ge: 1,
          le: 3600,
        },
      ],
    },
  ],

  capabilities: {
    alertOnFail: true,
    scheduling: true,
  },

  listView: {
    columns: [
      { key: 'id', label: 'ID', sortable: true },
      { key: 'service', label: 'Service', format: 'chip' },
      { key: 'schema', label: 'Schema', format: 'code' },
      { key: 'status', label: 'Status', format: 'status', sortable: true },
      { key: 'differences', label: 'Differences' },
      { key: 'lastRun', label: 'Last Run', format: 'relative', sortable: true },
    ],
    defaultSort: 'lastRun',
  },
};
