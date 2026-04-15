import { Routes, Route } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';
import { usePluginSchema, type PluginSchema } from '@sep/api';
import { PluginListPage } from './PluginListPage';
import { PluginCreatePage } from './PluginCreatePage';
import { PluginDetailPage } from './PluginDetailPage';

interface SchemaDrivenPluginProps {
  pluginName: string;
  mockSchema?: PluginSchema;
  mockTasks?: Record<string, unknown>[];
}

export function SchemaDrivenPlugin({ pluginName, mockSchema, mockTasks }: SchemaDrivenPluginProps) {
  const { data: schema, isLoading, error } = usePluginSchema(pluginName, mockSchema);

  if (isLoading && !schema) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error && !schema) {
    return (
      <Box sx={{ py: 4 }}>
        <Typography color="error">Failed to load plugin schema: {error.message}</Typography>
      </Box>
    );
  }

  if (!schema) {
    return null;
  }

  return (
    <Routes>
      <Route
        index
        element={<PluginListPage schema={schema} pluginName={pluginName} mockTasks={mockTasks} />}
      />
      <Route path="new" element={<PluginCreatePage schema={schema} pluginName={pluginName} />} />
      <Route
        path=":id"
        element={<PluginDetailPage schema={schema} pluginName={pluginName} mockTasks={mockTasks} />}
      />
    </Routes>
  );
}
