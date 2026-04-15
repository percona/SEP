import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import ScheduleIcon from '@mui/icons-material/Schedule';

interface ScheduledTasksPanelProps {
  pluginName: string;
}

// TODO: implement scheduled tasks management UI
export function ScheduledTasksPanel({ pluginName }: ScheduledTasksPanelProps) {
  return (
    <Paper variant="outlined" sx={{ p: 3, textAlign: 'center' }}>
      <ScheduleIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
      <Typography variant="h6" gutterBottom>
        Scheduled Tasks
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Configure recurring {pluginName} tasks with cron-based scheduling. This feature will be
        available when the backend supports task scheduling.
      </Typography>
    </Paper>
  );
}
