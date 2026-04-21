import { useParams, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import Skeleton from '@mui/material/Skeleton';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { usePluginTask, type PluginSchema } from '@sep/api';

interface PluginDetailPageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
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

export function PluginDetailPage({ schema, pluginName, mockTasks }: PluginDetailPageProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: task, isLoading } = usePluginTask(pluginName, id, mockTasks);

  if (isLoading) {
    return (
      <Box>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (!task) {
    return (
      <Box>
        <Typography variant="h5">Task not found</Typography>
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <IconButton onClick={() => navigate('..')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">
          {schema.displayName} #{id}
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
      </Box>

      <Paper sx={{ p: 3 }}>
        {schema.listView.columns.map((col) => (
          <DetailField key={col.key} label={col.label} value={task[col.key]} />
        ))}

        {/* Show any extra fields not in listView columns */}
        {Object.entries(task)
          .filter(([key]) => !schema.listView.columns.some((c) => c.key === key) && key !== 'id')
          .map(([key, value]) => (
            <DetailField key={key} label={key} value={value} />
          ))}
      </Paper>
    </Box>
  );
}
