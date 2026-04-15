import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useSnackbar } from 'notistack';
import { useCreatePluginTask, type PluginSchema } from '@sep/api';
import { SchemaFormRenderer } from '../SchemaFormRenderer';

interface PluginCreatePageProps {
  schema: PluginSchema;
  pluginName: string;
}

export function PluginCreatePage({ schema, pluginName }: PluginCreatePageProps) {
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const createTask = useCreatePluginTask(pluginName);

  const handleSubmit = (data: Record<string, unknown>) => {
    createTask.mutate(data, {
      onSuccess: () => {
        enqueueSnackbar(`${schema.displayName} task created`, { variant: 'success' });
        navigate('..');
      },
      onError: (error) => {
        enqueueSnackbar(error.message || 'Failed to create task', { variant: 'error' });
      },
    });
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <IconButton onClick={() => navigate('..')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">New {schema.displayName}</Typography>
      </Box>

      <SchemaFormRenderer
        sections={schema.forms}
        onSubmit={handleSubmit}
        loading={createTask.isPending}
        submitLabel={`Create ${schema.displayName}`}
      />
    </Box>
  );
}
