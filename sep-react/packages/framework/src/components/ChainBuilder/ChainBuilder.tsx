import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import LinkIcon from '@mui/icons-material/Link';

interface ChainBuilderProps {
  pluginName: string;
}

// TODO: implement visual chain builder for task chaining
export function ChainBuilder({ pluginName }: ChainBuilderProps) {
  return (
    <Paper variant="outlined" sx={{ p: 3, textAlign: 'center' }}>
      <LinkIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
      <Typography variant="h6" gutterBottom>
        Task Chaining
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Chain {pluginName} tasks with other plugins to create automated workflows.
        This feature will be available when the backend supports task chaining.
      </Typography>
    </Paper>
  );
}
