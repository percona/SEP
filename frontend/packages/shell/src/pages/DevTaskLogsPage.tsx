import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { TaskLogViewer } from '@sep/framework';
import { useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';

const STATUS_OPTIONS = ['RUNNING', 'SUCCESS', 'FAILED', 'STOPPED', 'LOST'];

export default function DevTaskLogsPage() {
  const params = useParams<{ id?: string }>();
  const [search, setSearch] = useSearchParams();

  const [id, setId] = useState(params.id ?? '');
  const status = search.get('status') ?? 'RUNNING';

  const activeId = params.id ?? id;

  return (
    <Container maxWidth="lg" sx={{ py: 3 }}>
      <Typography variant="h5" gutterBottom>
        Dev: TaskLogViewer
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Temporary dev-only page for exercising the TaskLogViewer against live SSE.
      </Typography>

      <Stack direction="row" spacing={2} sx={{ mb: 3 }} alignItems="flex-end">
        <TextField
          label="task_history_id"
          size="small"
          value={id}
          onChange={(e) => setId(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && id) {
              window.location.href = `/dev/task-logs/${encodeURIComponent(id)}?status=${status}`;
            }
          }}
        />
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>status</InputLabel>
          <Select
            label="status"
            value={status}
            onChange={(e) => {
              const next = new URLSearchParams(search);
              next.set('status', String(e.target.value));
              setSearch(next);
            }}
          >
            {STATUS_OPTIONS.map((s) => (
              <MenuItem key={s} value={s}>
                {s}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {activeId ? (
        <Box>
          <Typography variant="caption" color="text.secondary">
            id={activeId} · status={status}
          </Typography>
          <TaskLogViewer taskHistoryId={activeId} taskStatus={status} />
        </Box>
      ) : (
        <Typography variant="body2" color="text.secondary">
          Enter a task_history_id above to load.
        </Typography>
      )}
    </Container>
  );
}
