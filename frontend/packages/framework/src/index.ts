/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

// Components
export { SchemaFormRenderer } from './components/SchemaFormRenderer';
export { SchemaListView } from './components/SchemaListView';
export {
  SchemaDrivenPlugin,
  DeleteConfirmDialog,
  PluginCreatePage,
  PluginDetailPage,
  PluginListPage,
  PluginSchedulePage,
} from './components/SchemaDrivenPlugin';
export type { DeleteConfirmDialogProps } from './components/SchemaDrivenPlugin';
export { pathToEntityList } from './components/SchemaDrivenPlugin/PluginDetailPage';
export { ServiceSelector } from './components/ServiceSelector';
export type { ServiceSelectorProps } from './components/ServiceSelector';
export { SchemaSelector } from './components/SchemaSelector';
export type { SchemaSelectorProps } from './components/SchemaSelector';
export { TableSelector } from './components/TableSelector';
export type { TableSelectorProps } from './components/TableSelector';
export { HostSelector } from './components/HostSelector';
export {
  TaskLogViewer,
  LogStepTabs,
  LogOutputPane,
  ExecutionEventsPanel,
  StreamErrorBlock,
  StatusBadge,
} from './components/TaskLogViewer';
export type { TaskLogViewerProps, BadgeStatus } from './components/TaskLogViewer';
export {
  TaskHistoryTable,
  TaskHistoryStatusBadge,
  ChainDisplay,
} from './components/TaskHistoryTable';
export type {
  TaskHistoryTableProps,
  TaskHistoryEntry,
  TaskHistoryStatus,
  PaginatedTaskHistory,
} from './components/TaskHistoryTable';
export { ChainBuilder } from './components/ChainBuilder';

export type { ChainBuilderProps, ChainValue, AvailableTask } from './components/ChainBuilder';
export { AlertOnFailField, ALERT_ON_FAIL_FIELD_NAME } from './components/AlertOnFailField';
export { ScheduledTasksPanel } from './components/ScheduledTasksPanel';

// Hooks
export { useServices, useSchemas, useTables, useHosts } from './hooks';
export type {
  ServiceOption,
  ServiceType,
  SchemaOption,
  TableOption,
  HostOption,
  HostsResult,
  UseServicesOptions,
  UseSchemasOptions,
  UseTablesOptions,
  UseHostsOptions,
} from './hooks';

export {
  useTaskLogs,
  useExecutionEvents,
  useLogDownload,
  useTaskHistory,
  useTaskHistoryByName,
  useStopTaskHistory,
  isRunningStatus,
  RUNNING_STATUSES,
  useTaskHistoryFiles,
  useTaskFileDownload,
} from './hooks';
export type {
  TaskLogsState,
  StepText,
  LogType,
  FinishStatus,
  StreamError,
  StreamStatus,
  ExecutionEvent,
  ExecutionEventsState,
  DownloadLog,
  FileMetadata,
  TaskHistoryFilesMap,
  TaskFileDownloadParams,
} from './hooks';
