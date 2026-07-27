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

import type { SectionField, SepComponents } from '@sep/api';

type Schemas = SepComponents['schemas'];

// ── Category browser ─────────────────────────────────────────────────────

export interface AtwSnippetSummary {
  /** Snippet filename; use with snippets app API path helpers. */
  name: string;
  title: string;
  description: string;
}

export interface AtwCategoryListing {
  category_root: string;
  parent_category: string;
  parent_category_label: string;
  category: string;
  category_label: string;
  snippet_count: number;
  snippets: AtwSnippetSummary[];
}

// ── Incidents ────────────────────────────────────────────────────────────

export type AtwIncident = Schemas['atw__AtwIncidentResponse'];
export type AtwIncidentWrite = Schemas['atw__AtwIncidentWrite'];
export type AtwIncidentUpdate = Schemas['atw__AtwIncidentUpdate'];

// ── Merged execution schema ──────────────────────────────────────────────

/**
 * The merged execution form for a batch selection. `shared` holds the
 * batch-level execution fields plus every parameter the selection declares
 * identically; `per_snippet` holds each snippet's remaining fields. The wire
 * field union matches the framework `SectionField` shape the SchemaFormRenderer
 * consumes, so both arrays are typed as `SectionField[]`.
 */
export interface AtwMergedSchema {
  shared: SectionField[];
  per_snippet: AtwSnippetSchema[];
}

export interface AtwSnippetSchema {
  snippet_filename: string;
  fields: SectionField[];
}

// ── Batch execution ──────────────────────────────────────────────────────

export type AtwBatchExecuteWrite = Schemas['atw__ATWBatchExecuteWrite'];
export type AtwBatchExecuteItemWrite = Schemas['atw__ATWBatchExecuteItemWrite'];
export type AtwBatchExecuteResponse = Schemas['atw__ATWBatchExecuteResponse'];
export type AtwBatchExecuteItemResponse = Schemas['atw__ATWBatchExecuteItemResponse'];

// ── Incident execution history ───────────────────────────────────────────

export type AtwIncidentExecution = Schemas['atw__ATWIncidentExecutionResponse'];
