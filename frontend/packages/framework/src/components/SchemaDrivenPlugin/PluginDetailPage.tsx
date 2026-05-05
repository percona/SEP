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

import { useMemo, type ReactNode } from 'react';
import { format as formatSql } from 'sql-formatter';
import { Highlight, themes } from 'prism-react-renderer';
import { useParams, useNavigate, useLocation, Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import IconButton from '@mui/material/IconButton';
import Button from '@mui/material/Button';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import Skeleton from '@mui/material/Skeleton';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import EditIcon from '@mui/icons-material/Edit';
import {
  useDeletePluginEntity,
  usePluginEntityDetail,
  usePluginTask,
  type PluginEntitySchema,
  type PluginSchema,
} from '@sep/api';
import { detailPrism } from './detailPrism';

export interface PluginDetailPageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
  /** Hide edit/delete (browse-only mode for multi-entity plugins). */
  browseOnly?: boolean;
  /** Omit these keys from the auto-rendered detail section (e.g. nested relations shown elsewhere). */
  suppressDetailKeys?: string[];
  /** Extra content under the main detail card (e.g. child entity tables). */
  renderEntityDetailChildren?: (args: {
    entityName: string;
    record: Record<string, unknown>;
    schema: PluginSchema;
    pathname: string;
    pluginName: string;
    mockEntityItems?: Record<string, Record<string, unknown>[]>;
    allowListEntityDelete?: boolean;
  }) => ReactNode;
  /** Nested inventory: resolve ``entityName`` / ``id`` from named params (e.g. ``nodeId``). */
  detailEntityName?: string;
  detailIdParam?: string;
  /** Optional callback that resolves a custom back/delete target from current pathname. */
  resolveParentPath?: (pathname: string) => string | null;
  /** When true, omit the header row (back button, ``{title} #{id}``, status chip, edit/delete). */
  hideDetailChrome?: boolean;
  /** When true, nested list tables may show row delete (inventory ``actions`` column). */
  allowListEntityDelete?: boolean;
}

/** Screen title when the back/status row is hidden (e.g. inventory browse-only). */
function detailScreenHeading(
  entityName: string | undefined,
  entityDisplayName: string | undefined,
): string | null {
  if (!entityName) {
    return null;
  }
  const known: Record<string, string> = {
    nodes: 'Node detail',
    services: 'Service detail',
    schemas: 'Schema detail',
    tables: 'Table detail',
  };
  return known[entityName] ?? `${entityDisplayName ?? entityName} detail`;
}

/** List URL for the current entity tab (path segment before ``:id``), e.g. ``/inventory/services``. */
export function pathToEntityList(pathname: string, entityName: string): string {
  const parts = pathname.split('/').filter(Boolean);
  const idx = parts.lastIndexOf(entityName);
  if (idx < 0) {
    return '/';
  }
  return `/${parts.slice(0, idx + 1).join('/')}`;
}

const detailCodeBlockSx = {
  fontFamily: "'Roboto Mono', ui-monospace, monospace",
  fontSize: '0.8125rem',
  lineHeight: 1.6,
  whiteSpace: 'pre-wrap' as const,
  wordBreak: 'break-word' as const,
  p: 2,
  mt: 0.5,
  borderRadius: 1,
  bgcolor: 'action.hover',
  border: 1,
  borderColor: 'divider',
  overflowX: 'auto' as const,
};

function formatCreateSql(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) {
    return raw;
  }
  try {
    return formatSql(trimmed, { language: 'mysql', tabWidth: 2 });
  } catch {
    return raw;
  }
}

function formatKeysForDisplay(value: unknown): string {
  if (typeof value === 'string') {
    const t = value.trim();
    if (!t) {
      return value;
    }
    try {
      return JSON.stringify(JSON.parse(t), null, 2);
    } catch {
      return value;
    }
  }
  if (value !== null && typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

type DetailSyntaxLanguage = 'sql' | 'json';

function formatDetailSyntaxCode(value: unknown, language: DetailSyntaxLanguage): string {
  if (language === 'sql') {
    return typeof value === 'string' ? formatCreateSql(value) : String(value);
  }
  return formatKeysForDisplay(value);
}

function DetailSyntaxBlock({ code, language }: { code: string; language: DetailSyntaxLanguage }) {
  const muiTheme = useTheme();
  const prismTheme = muiTheme.palette.mode === 'dark' ? themes.vsDark : themes.vsLight;

  return (
    <Highlight prism={detailPrism} theme={prismTheme} code={code} language={language}>
      {({ className, style, tokens, getLineProps, getTokenProps }) => (
        <Box
          component="pre"
          className={className}
          style={style}
          sx={{
            ...detailCodeBlockSx,
            margin: 0,
          }}
        >
          {tokens.map((line, i) => (
            <div key={i} {...getLineProps({ line })}>
              {line.map((token, key) => (
                <span key={key} {...getTokenProps({ token })} />
              ))}
            </div>
          ))}
        </Box>
      )}
    </Highlight>
  );
}

function DetailField({
  label,
  value,
  highlightLanguage,
}: {
  label: string;
  value: unknown;
  highlightLanguage?: DetailSyntaxLanguage;
}) {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  if (highlightLanguage) {
    return (
      <Box sx={{ mb: 2 }}>
        <Typography variant="caption" color="text.secondary">
          {label}
        </Typography>
        <DetailSyntaxBlock
          code={formatDetailSyntaxCode(value, highlightLanguage)}
          language={highlightLanguage}
        />
      </Box>
    );
  }

  let display: React.ReactNode;
  if (typeof value === 'boolean') {
    display = value ? 'Yes' : 'No';
  } else if (typeof value === 'object') {
    display = <DetailSyntaxBlock code={JSON.stringify(value, null, 2)} language="json" />;
  } else {
    display = String(value);
  }

  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      {typeof value === 'object' ? display : <Typography variant="body1">{display}</Typography>}
    </Box>
  );
}

export function PluginDetailPage({
  schema,
  pluginName,
  mockTasks,
  mockEntityItems,
  browseOnly = false,
  suppressDetailKeys = [],
  renderEntityDetailChildren,
  detailEntityName,
  detailIdParam,
  resolveParentPath,
  hideDetailChrome = false,
  allowListEntityDelete = false,
}: PluginDetailPageProps) {
  const params = useParams<Record<string, string | undefined>>();
  const id = (detailIdParam && params[detailIdParam]) ?? params.id;
  const entityName = detailEntityName ?? params.entityName;
  const navigate = useNavigate();
  const location = useLocation();
  const entitySchema = useMemo(
    () => schema.entities?.find((e: PluginEntitySchema) => e.name === entityName),
    [schema.entities, entityName],
  );
  const multi = Boolean(schema.entities?.length && entityName && entitySchema);

  const customParentPath = useMemo(() => {
    if (!resolveParentPath) {
      return null;
    }
    return resolveParentPath(location.pathname);
  }, [location.pathname, resolveParentPath]);

  const taskQuery = usePluginTask(pluginName, id, mockTasks, { enabled: !multi && Boolean(id) });
  const entityQuery = usePluginEntityDetail(
    pluginName,
    entityName ?? '',
    id,
    multi ? mockEntityItems?.[entityName!] : undefined,
    { enabled: multi && Boolean(id) },
  );

  const { data: task, isLoading } = multi ? entityQuery : taskQuery;
  const listView = multi ? entitySchema!.listView : schema.listView!;
  const title = multi ? entitySchema!.displayName : schema.displayName;
  const headingWhenChromeHidden = useMemo(
    () =>
      hideDetailChrome && multi ? detailScreenHeading(entityName, entitySchema?.displayName) : null,
    [hideDetailChrome, multi, entityName, entitySchema?.displayName],
  );

  const deleteEntity = useDeletePluginEntity(
    pluginName,
    entityName ?? '',
    multi ? mockEntityItems?.[entityName!] : undefined,
  );

  const handleDelete = () => {
    if (!id || !multi) {
      return;
    }
    if (!window.confirm(`Delete ${title} #${id}? This cannot be undone.`)) {
      return;
    }
    deleteEntity.mutate(id, {
      onSuccess: () =>
        customParentPath
          ? navigate(customParentPath)
          : entityName
            ? navigate(pathToEntityList(location.pathname, entityName))
            : navigate('..', { relative: 'path' }),
    });
  };

  if (isLoading) {
    return (
      <Box>
        {headingWhenChromeHidden ? (
          <Typography component="h1" variant="h4" sx={{ mb: 2, fontWeight: 600 }}>
            {headingWhenChromeHidden}
          </Typography>
        ) : (
          <Skeleton variant="text" width={300} height={40} />
        )}
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (!task) {
    return (
      <Box>
        {headingWhenChromeHidden ? (
          <Typography component="h1" variant="h4" sx={{ mb: 2, fontWeight: 600 }}>
            {headingWhenChromeHidden}
          </Typography>
        ) : null}
        <Typography variant="h5">Not found</Typography>
      </Box>
    );
  }

  return (
    <Box>
      {headingWhenChromeHidden ? (
        <Typography component="h1" variant="h4" sx={{ mb: 2, fontWeight: 600 }}>
          {headingWhenChromeHidden}
        </Typography>
      ) : null}
      {!hideDetailChrome && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3, flexWrap: 'wrap' }}>
          <IconButton
            onClick={() =>
              customParentPath
                ? navigate(customParentPath)
                : multi && entityName
                  ? navigate(pathToEntityList(location.pathname, entityName))
                  : navigate('..', { relative: 'path' })
            }
          >
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h4">
            {title} #{id}
          </Typography>
          {typeof task.status === 'string' && (
            <Chip
              label={task.status}
              size="small"
              color={
                task.status === 'completed' || task.status === 'success'
                  ? 'success'
                  : task.status === 'failed'
                    ? 'error'
                    : 'default'
              }
            />
          )}
          {multi && !browseOnly && (
            <>
              <Button
                component={RouterLink}
                to="edit"
                relative="path"
                startIcon={<EditIcon />}
                variant="outlined"
                size="small"
              >
                Edit
              </Button>
              <Button color="error" variant="outlined" size="small" onClick={handleDelete}>
                Delete
              </Button>
            </>
          )}
        </Box>
      )}

      <Paper sx={{ p: 3 }}>
        {listView.columns
          .filter((col) => col.format !== 'actions' && col.key !== '_actions')
          .map((col) => (
            <DetailField
              key={col.key}
              highlightLanguage={entitySchema?.detailHighlights?.[col.key]}
              label={col.label}
              value={task[col.key]}
            />
          ))}

        {Object.entries(task)
          .filter(
            ([key]) =>
              !listView.columns.some((c) => c.key === key) &&
              key !== 'id' &&
              key !== '_actions' &&
              !suppressDetailKeys.includes(key),
          )
          .map(([key, value]) => (
            <DetailField
              key={key}
              highlightLanguage={entitySchema?.detailHighlights?.[key]}
              label={key}
              value={value}
            />
          ))}
      </Paper>

      {multi &&
        entityName &&
        renderEntityDetailChildren &&
        renderEntityDetailChildren({
          entityName,
          record: task as Record<string, unknown>,
          schema,
          pathname: location.pathname,
          pluginName,
          mockEntityItems,
          allowListEntityDelete,
        })}
    </Box>
  );
}
