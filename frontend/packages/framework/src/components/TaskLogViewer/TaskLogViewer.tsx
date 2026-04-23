import DownloadIcon from '@mui/icons-material/Download';
import Badge from '@mui/material/Badge';
import Box from '@mui/material/Box';
import FormControlLabel from '@mui/material/FormControlLabel';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Tooltip from '@mui/material/Tooltip';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useExecutionEvents } from '../../hooks/useExecutionEvents';
import { useLogDownload } from '../../hooks/useLogDownload';
import { useTaskLogs, type LogType } from '../../hooks/useTaskLogs';
import { ExecutionEventsPanel } from './ExecutionEventsPanel';
import { LogOutputPane } from './LogOutputPane';
import { LogStepTabs } from './LogStepTabs';
import { StatusBadge, type BadgeStatus } from './StatusBadge';
import { StreamErrorBlock } from './StreamErrorBlock';

type TopTab = 'stdout' | 'stderr' | 'events';

export interface TaskLogViewerProps {
  taskHistoryId: number | string;
  taskStatus?: string;
  height?: number | string;
}

function isRunningStatus(status?: string): boolean {
  return (status ?? '').toLowerCase() === 'running';
}

function resolveBadgeStatus(
  finishStatus: ReturnType<typeof useTaskLogs>['finishStatus'],
  error: ReturnType<typeof useTaskLogs>['error'],
): BadgeStatus | undefined {
  if (error) {
    return error.code === 410 ? 'executor-gone' : 'stream-error';
  }
  return finishStatus;
}

export function TaskLogViewer({ taskHistoryId, taskStatus, height = 480 }: TaskLogViewerProps) {
  const running = isRunningStatus(taskStatus);
  const { textByStep, stepOrder, finishStatus, error } = useTaskLogs(taskHistoryId);
  const { eventsByStep, stepOrder: eventStepOrder } = useExecutionEvents(taskHistoryId, running);

  const [topTab, setTopTab] = useState<TopTab>('stdout');
  const [activeStep, setActiveStep] = useState<string | undefined>();
  const [wrap, setWrap] = useState(false);

  const [unreadTypes, setUnreadTypes] = useState<Set<LogType>>(new Set());
  const [unreadEvents, setUnreadEvents] = useState(false);
  const [unreadSteps, setUnreadSteps] = useState<Set<string>>(new Set());

  const prevLogSizesRef = useRef<Record<string, number>>({});
  const prevEventCountRef = useRef(0);

  // Reset view state when switching to a different task history
  useEffect(() => {
    setActiveStep(undefined);
    setUnreadTypes(new Set());
    setUnreadSteps(new Set());
    setUnreadEvents(false);
    prevLogSizesRef.current = {};
    prevEventCountRef.current = 0;
  }, [taskHistoryId]);

  useEffect(() => {
    if (!activeStep && stepOrder.length > 0) {
      setActiveStep(stepOrder[0]);
    }
  }, [stepOrder, activeStep]);

  // Track unread notifications based on accumulated text growth
  useEffect(() => {
    for (const step of stepOrder) {
      const pane = textByStep[step];
      if (!pane) {
        continue;
      }
      (['stdout', 'stderr'] as const).forEach((type) => {
        const key = `${step}_${type}`;
        const size = pane[type].length;
        const prev = prevLogSizesRef.current[key] ?? 0;
        if (size > prev) {
          if (topTab !== type) {
            setUnreadTypes((prevSet) => {
              if (prevSet.has(type)) {
                return prevSet;
              }
              const next = new Set(prevSet);
              next.add(type);
              return next;
            });
          }
          if (activeStep !== step) {
            setUnreadSteps((prevSet) => {
              if (prevSet.has(step)) {
                return prevSet;
              }
              const next = new Set(prevSet);
              next.add(step);
              return next;
            });
          }
        }
        prevLogSizesRef.current[key] = size;
      });
    }
  }, [textByStep, stepOrder, topTab, activeStep]);

  // Events unread badge on top tab
  useEffect(() => {
    const total = Object.values(eventsByStep).reduce((sum, list) => sum + list.length, 0);
    if (total > prevEventCountRef.current && topTab !== 'events') {
      setUnreadEvents(true);
    }
    prevEventCountRef.current = total;
  }, [eventsByStep, topTab]);

  const handleTopTab = (value: TopTab) => {
    setTopTab(value);
    if (value === 'events') {
      setUnreadEvents(false);
    } else {
      setUnreadTypes((prev) => {
        if (!prev.has(value)) {
          return prev;
        }
        const next = new Set(prev);
        next.delete(value);
        return next;
      });
    }
  };

  const handleStepSelect = (step: string) => {
    setActiveStep(step);
    setUnreadSteps((prev) => {
      if (!prev.has(step)) {
        return prev;
      }
      const next = new Set(prev);
      next.delete(step);
      return next;
    });
  };

  const stepsForTabs = useMemo(() => {
    if (topTab === 'events') {
      return eventStepOrder.filter((s) => s !== '');
    }
    return stepOrder;
  }, [topTab, eventStepOrder, stepOrder]);

  const currentPaneText = useMemo(() => {
    if (topTab === 'events' || !activeStep) {
      return '';
    }
    const pane = textByStep[activeStep];
    if (!pane) {
      return '';
    }
    return pane[topTab] ?? '';
  }, [textByStep, activeStep, topTab]);

  const download = useLogDownload();
  const handleDownload = () => {
    if (topTab === 'events') {
      return;
    }
    const filename = `task-${taskHistoryId}-${activeStep ?? 'step'}-${topTab}.log`;
    download(filename, currentPaneText);
  };

  const badgeStatus = resolveBadgeStatus(finishStatus, error);

  return (
    <Paper variant="outlined" sx={{ display: 'flex', flexDirection: 'column' }}>
      <Stack
        direction="row"
        alignItems="center"
        sx={{ px: 1, pt: 1, borderBottom: 1, borderColor: 'divider' }}
      >
        <Tabs
          value={topTab}
          onChange={(_, v: TopTab) => handleTopTab(v)}
          sx={{ flex: 1, minHeight: 40 }}
        >
          <Tab
            value="stdout"
            label={
              <Badge color="primary" variant="dot" invisible={!unreadTypes.has('stdout')}>
                <span>stdout</span>
              </Badge>
            }
          />
          <Tab
            value="stderr"
            label={
              <Badge color="primary" variant="dot" invisible={!unreadTypes.has('stderr')}>
                <span>stderr</span>
              </Badge>
            }
          />
          <Tab
            value="events"
            label={
              <Badge color="primary" variant="dot" invisible={!unreadEvents}>
                <span>Execution events</span>
              </Badge>
            }
          />
        </Tabs>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ pr: 1 }}>
          {badgeStatus && <StatusBadge status={badgeStatus} />}
          <FormControlLabel
            control={
              <Switch size="small" checked={wrap} onChange={(_, checked) => setWrap(checked)} />
            }
            label="Wrap"
            slotProps={{ typography: { variant: 'body2' } }}
          />
          <Tooltip title="Download log">
            <span>
              <IconButton
                size="small"
                onClick={handleDownload}
                disabled={topTab === 'events' || !currentPaneText}
                aria-label="Download log"
              >
                <DownloadIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
      </Stack>

      {error && (
        <Box sx={{ p: 1 }}>
          <StreamErrorBlock error={error} />
        </Box>
      )}

      <Box sx={{ flex: 1, minHeight: 0 }}>
        {topTab === 'events' ? (
          <ExecutionEventsPanel
            eventsByStep={eventsByStep}
            activeStep={activeStep}
            height={height}
          />
        ) : (
          <LogOutputPane text={currentPaneText} wrap={wrap} height={height} />
        )}
      </Box>

      <Box sx={{ borderTop: 1, borderColor: 'divider', px: 1 }}>
        <LogStepTabs
          steps={stepsForTabs}
          activeStep={activeStep}
          unreadSteps={unreadSteps}
          onSelect={handleStepSelect}
        />
      </Box>
    </Paper>
  );
}
