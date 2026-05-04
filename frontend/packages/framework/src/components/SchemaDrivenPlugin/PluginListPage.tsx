import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import AddIcon from '@mui/icons-material/Add';
import { usePluginEntityList, usePluginTasks, type PluginSchema } from '@sep/api';
import { SchemaListView } from '../SchemaListView';

interface PluginListPageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
  /** When true, hide the create action and row navigation to detail. */
  listOnly?: boolean;
  /** When true, hide only the create button (row navigation still enabled). */
  hideCreate?: boolean;
  /** When true, hide entity tabs (nodes / services / …). */
  hideEntityTabs?: boolean;
  /** When set, overrides ``useParams().entityName`` (nested routes that use a fixed segment like ``nodes``). */
  entityNameOverride?: string;
  /**
   * When set, row clicks navigate to this absolute path (e.g. nested inventory:
   * ``(row) => \`\${pathname}/\${row.id}\```).
   */
  rowClickHref?: (row: Record<string, unknown>) => string;
}

export function PluginListPage({
  schema,
  pluginName,
  mockTasks,
  mockEntityItems,
  listOnly = false,
  hideCreate = false,
  hideEntityTabs = false,
  entityNameOverride,
  rowClickHref,
}: PluginListPageProps) {
  const navigate = useNavigate();
  const { entityName: entityNameParam } = useParams<{ entityName?: string }>();
  const entityName = entityNameOverride ?? entityNameParam;
  const entitySchema = useMemo(
    () => schema.entities?.find((e) => e.name === entityName),
    [schema.entities, entityName],
  );
  const multi = Boolean(schema.entities?.length && entityName && entitySchema);

  const singleQuery = usePluginTasks(pluginName, mockTasks, { enabled: !multi });
  const entityQuery = usePluginEntityList(
    pluginName,
    entityName ?? '',
    multi ? mockEntityItems?.[entityName!] : undefined,
    { enabled: multi },
  );

  const { data: rows = [], isLoading } = multi ? entityQuery : singleQuery;
  const listView = multi ? entitySchema!.listView : schema.listView!;
  const title = multi ? entitySchema!.displayName : schema.displayName;
  const description = multi ? entitySchema?.description : schema.description;

  return (
    <Box>
      {multi && schema.entities && !hideEntityTabs && (
        <Tabs
          sx={{ mb: 2 }}
          value={entityName}
          onChange={(_, value) => {
            if (typeof value === 'string' && value !== entityName) {
              navigate(`../${value}`, { relative: 'path' });
            }
          }}
          variant="scrollable"
          scrollButtons="auto"
        >
          {schema.entities.map((e) => (
            <Tab key={e.name} label={e.displayName} value={e.name} />
          ))}
        </Tabs>
      )}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          mb: 3,
          gap: 2,
        }}
      >
        <Box>
          <Typography variant="h4">{title}</Typography>
          {description && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {description}
            </Typography>
          )}
        </Box>
        {!listOnly && !hideCreate && (
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => navigate('new', { relative: 'path' })}
          >
            New {title}
          </Button>
        )}
      </Box>

      <SchemaListView
        listView={listView}
        data={rows}
        isLoading={isLoading}
        onRowClick={
          listOnly
            ? undefined
            : (row) =>
                rowClickHref
                  ? navigate(rowClickHref(row as Record<string, unknown>))
                  : navigate(String(row.id), { relative: 'path' })
        }
      />
    </Box>
  );
}
