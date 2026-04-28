import type {
  PaginatedTaskHistory,
  TaskHistoryEntry,
  TaskHistoryStatus,
} from '../../hooks/useTaskHistory';

export type { PaginatedTaskHistory, TaskHistoryEntry, TaskHistoryStatus };

export interface TaskHistoryTableProps {
  /** Optional task name to scope the listing to a single task. */
  taskName?: string;
  /** Optional explicit data — bypasses the internal React Query hook (used in stories/tests). */
  data?: TaskHistoryEntry[];
  /** Server-side status filter (applied via the React Query hook). */
  statusFilter?: TaskHistoryStatus | null;
  /** Loading flag (only honored when `data` is provided). */
  isLoading?: boolean;
  /** Override polling interval in ms. Default 5000. */
  pollingIntervalMs?: number;
  /** Force-disable polling regardless of running tasks. */
  disablePolling?: boolean;
  /** Resolver from Casdoor user id → display name. */
  resolveUserName?: (userId: string | null | undefined) => string;
  /** Action callback: view logs for a row. */
  onViewLogs?: (entry: TaskHistoryEntry) => void;
  /** Action callback: stop a running task. */
  onStopTask?: (entry: TaskHistoryEntry) => void;
  /** Action callback: open download dialog. */
  onDownloadFiles?: (entry: TaskHistoryEntry) => void;
  /** Action callback: navigate to chained task by name. */
  onChainItemClick?: (taskName: string, index: number, entry: TaskHistoryEntry) => void;
  /** Hide the Task Name column (useful when scoped to a single task). */
  hideTaskNameColumn?: boolean;
}
