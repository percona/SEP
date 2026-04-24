import { LazyLog } from '@melloware/react-logviewer';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

export interface LogOutputPaneProps {
  text: string;
  wrap: boolean;
  enableSearch?: boolean;
  height?: number | string;
  emptyLabel?: string;
}

export function LogOutputPane({
  text,
  wrap,
  enableSearch = true,
  height = 400,
  emptyLabel = 'No output yet.',
}: LogOutputPaneProps) {
  if (!text) {
    return (
      <Box sx={{ p: 2, color: 'text.secondary' }}>
        <Typography variant="body2">{emptyLabel}</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ height, width: '100%' }}>
      <LazyLog
        text={text}
        extraLines={1}
        enableSearch={enableSearch}
        wrapLines={wrap}
        follow
        selectableLines
        caseInsensitive
      />
    </Box>
  );
}
