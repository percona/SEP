import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useSnackbar } from 'notistack';
import { useCreatePluginEntity, useCreatePluginTask, type PluginSchema } from '@sep/api';
import { SchemaFormRenderer } from '../SchemaFormRenderer';

interface PluginCreatePageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
}

export function PluginCreatePage({
  schema,
  pluginName,
  mockTasks,
  mockEntityItems,
}: PluginCreatePageProps) {
  const navigate = useNavigate();
  const { entityName } = useParams<{ entityName?: string }>();
  const entitySchema = useMemo(
    () => schema.entities?.find((e) => e.name === entityName),
    [schema.entities, entityName],
  );
  const multi = Boolean(schema.entities?.length && entityName && entitySchema);
  const { enqueueSnackbar } = useSnackbar();
  const createTask = useCreatePluginTask(pluginName, mockTasks);
  const createEntity = useCreatePluginEntity(
    pluginName,
    entityName ?? '',
    multi ? mockEntityItems?.[entityName!] : undefined,
  );

  const create = multi ? createEntity : createTask;
  const title = multi ? entitySchema!.displayName : schema.displayName;
  const sections = multi ? entitySchema!.forms : schema.forms!;

  const handleSubmit = (data: Record<string, unknown>) => {
    create.mutate(data, {
      onSuccess: () => {
        enqueueSnackbar(`${title} created`, { variant: 'success' });
        navigate('..', { relative: 'path' });
      },
      onError: (error: unknown) => {
        const message = error instanceof Error ? error.message : 'Failed to create';
        enqueueSnackbar(message, { variant: 'error' });
      },
    });
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <IconButton onClick={() => navigate('..', { relative: 'path' })}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">New {title}</Typography>
      </Box>

      <SchemaFormRenderer
        sections={sections}
        onSubmit={handleSubmit}
        loading={create.isPending}
        submitLabel={`Create ${title}`}
      />
    </Box>
  );
}
