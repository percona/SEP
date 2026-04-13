import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import type { PluginSchema } from '@sep/api';
import { usePluginTasks } from '@sep/api';
import { SchemaListView } from '../SchemaListView';

interface PluginListPageProps {
  schema: PluginSchema;
  pluginName: string;
  mockTasks?: Record<string, unknown>[];
}

export function PluginListPage({ schema, pluginName, mockTasks }: PluginListPageProps) {
  const navigate = useNavigate();
  const { data: tasks = [], isLoading } = usePluginTasks(pluginName, mockTasks);

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4">{schema.displayName}</Typography>
          {schema.description && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {schema.description}
            </Typography>
          )}
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => navigate('new')}
        >
          New {schema.displayName}
        </Button>
      </Box>

      <SchemaListView
        listView={schema.listView}
        data={tasks}
        isLoading={isLoading}
        onRowClick={(row) => navigate(String(row.id))}
      />
    </Box>
  );
}
