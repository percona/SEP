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

import { useNavigate, useParams } from 'react-router-dom';
import { Alert, Box, Link as MuiLink } from '@mui/material';
import { SnippetExecutionAccordion } from '@sep/framework';
import { useSnippetSchema } from './hooks';

/**
 * Snippet detail page rendered at `/snippets/:filename`.
 *
 * Delegates form rendering, execution, log streaming, and history display
 * to ``SnippetExecutionAccordion``. No ``executorHost`` prop is passed, so
 * the accordion renders the schema-driven host selector field.
 *
 * The legacy Jinja2 detail page remains mounted for capabilities not yet
 * ported (chaining, scheduling, alerting).
 */
export function SnippetDetailPage() {
  const { filename } = useParams<{ filename: string }>();
  const navigate = useNavigate();
  const schemaQuery = useSnippetSchema(filename);

  if (!filename) {
    return <Alert severity="error">Missing snippet filename in the URL.</Alert>;
  }

  const displayTitle = schemaQuery.data?.display_name ?? filename;
  const description = schemaQuery.data?.description;

  return (
    <Box>
      <MuiLink
        component="button"
        type="button"
        onClick={() => navigate('..')}
        sx={{ mb: 2, display: 'inline-block' }}
      >
        ← Back to snippets
      </MuiLink>

      <SnippetExecutionAccordion
        snippetFilename={filename}
        title={displayTitle}
        description={description}
        defaultExpanded
        showHistory
      />
    </Box>
  );
}
