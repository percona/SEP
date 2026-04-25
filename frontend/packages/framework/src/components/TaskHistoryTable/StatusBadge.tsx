import AutorenewIcon from '@mui/icons-material/Autorenew';
import CancelIcon from '@mui/icons-material/Cancel';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import HourglassDisabledIcon from '@mui/icons-material/HourglassDisabled';
import ReportIcon from '@mui/icons-material/Report';
import Chip from '@mui/material/Chip';
import type { TaskHistoryStatus } from '../../hooks/useTaskHistory';

type ChipColor = 'success' | 'error' | 'warning' | 'info' | 'default';

interface StatusEntry {
  label: string;
  color: ChipColor;
  icon: React.ReactElement;
  spin?: boolean;
}

const STATUS_MAP: Record<TaskHistoryStatus, StatusEntry> = {
  success: { label: 'Done', color: 'success', icon: <CheckCircleIcon /> },
  failed: { label: 'Failed', color: 'error', icon: <ReportIcon /> },
  running: { label: 'Running', color: 'info', icon: <AutorenewIcon />, spin: true },
  pending: { label: 'Pending', color: 'default', icon: <HourglassEmptyIcon /> },
  stopped: { label: 'Stopped', color: 'warning', icon: <CancelIcon /> },
  lost: { label: 'Lost', color: 'default', icon: <HelpOutlineIcon /> },
  stale: { label: 'Stale', color: 'default', icon: <HourglassDisabledIcon /> },
};

export interface StatusBadgeProps {
  status: TaskHistoryStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const entry = STATUS_MAP[status];
  return (
    <Chip
      size="small"
      color={entry.color}
      icon={entry.icon}
      label={entry.label}
      data-status={status}
      sx={
        entry.spin
          ? {
              '& .MuiChip-icon': {
                animation: 'taskHistorySpin 1.4s linear infinite',
              },
              '@keyframes taskHistorySpin': {
                from: { transform: 'rotate(0deg)' },
                to: { transform: 'rotate(360deg)' },
              },
            }
          : undefined
      }
    />
  );
}
