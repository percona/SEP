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
  display_name: 'Checksums',
  description: 'Run pt-table-checksum to verify data consistency between MySQL replicas.',
  task_type: 'pt-table-checksum',

  forms: [
    {
      title: 'Target',
      description: 'Select the MySQL service to run checksums against.',
      fields: [
        {
          name: 'service_id',
          label: 'MySQL Service',
          type: 'service',
          required: true,
          service_types: ['mysql'],
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
          name: 'chunk_size',
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
          name: 'replicate_check',
          label: 'Replicate check (--replicate-check)',
          type: 'bool',
          default: true,
        },
        {
          name: 'check_interval',
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
    alert_on_fail: true,
    scheduling: true,
  },

  list_view: {
    columns: [
      { key: 'id', label: 'ID', sortable: true },
      { key: 'service', label: 'Service', format: 'chip' },
      { key: 'schema', label: 'Schema', format: 'code' },
      { key: 'status', label: 'Status', format: 'status', sortable: true },
      { key: 'differences', label: 'Differences' },
      { key: 'last_run', label: 'Last Run', format: 'relative', sortable: true },
    ],
    default_sort: '-last_run',
  },
};
