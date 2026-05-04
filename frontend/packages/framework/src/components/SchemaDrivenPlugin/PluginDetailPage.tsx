import { useMemo, type ReactNode } from 'react';
import { useParams, useNavigate, useLocation, Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
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
import { inventoryMountPrefix, pathToNestedInventoryParent } from './inventoryNestedPaths';

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
  }) => ReactNode;
  /** Nested inventory: resolve ``entityName`` / ``id`` from named params (e.g. ``nodeId``). */
  detailEntityName?: string;
  detailIdParam?: string;
  /** When true, back/delete target the nested inventory parent path instead of flat entity list. */
  useNestedInventoryNavigation?: boolean;
  /** When true, omit the header row (back button, ``{title} #{id}``, status chip, edit/delete). */
  hideDetailChrome?: boolean;
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

function DetailField({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === '') {
    return null;
  }

  let display: React.ReactNode;
  if (typeof value === 'boolean') {
    display = value ? 'Yes' : 'No';
  } else if (typeof value === 'object') {
    display = (
      <Typography
        component="pre"
        variant="body2"
        sx={{ fontFamily: "'Roboto Mono', monospace", whiteSpace: 'pre-wrap' }}
      >
        {JSON.stringify(value, null, 2) as string}
      </Typography>
    );
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
  useNestedInventoryNavigation = false,
  hideDetailChrome = false,
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

  const nestedParentPath = useMemo(() => {
    if (!useNestedInventoryNavigation) {
      return null;
    }
    const prefix = inventoryMountPrefix(location.pathname);
    return prefix ? pathToNestedInventoryParent(location.pathname, prefix) : null;
  }, [location.pathname, useNestedInventoryNavigation]);

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
        nestedParentPath
          ? navigate(nestedParentPath)
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
              nestedParentPath
                ? navigate(nestedParentPath)
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
        {listView.columns.map((col) => (
          <DetailField key={col.key} label={col.label} value={task[col.key]} />
        ))}

        {Object.entries(task)
          .filter(
            ([key]) =>
              !listView.columns.some((c) => c.key === key) &&
              key !== 'id' &&
              !suppressDetailKeys.includes(key),
          )
          .map(([key, value]) => (
            <DetailField key={key} label={key} value={value} />
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
        })}
    </Box>
  );
}
