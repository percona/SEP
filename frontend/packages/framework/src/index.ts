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

// Constants
export { SEP_TABLE_CLASS } from './constants';

// Components
export { SchemaFormRenderer } from './components/SchemaFormRenderer';
export type { RenderFieldArgs, RenderFieldOverride } from './components/SchemaFormRenderer';
export { SchemaListView } from './components/SchemaListView';
export type { RenderListColumnArgs, RenderListColumnOverride } from './components/SchemaListView';
export {
  SchemaDrivenApp,
  DeleteConfirmDialog,
  AppCreatePage,
  AppDetailPage,
  AppListPage,
  AppSchedulePage,
} from './components/SchemaDrivenApp';
export type { AppFormSlotProps, RenderFormSlot } from './components/SchemaDrivenApp';
export type { DeleteConfirmDialogProps } from './components/SchemaDrivenApp';
export type { TaskExecuteAction } from './components/SchemaDrivenApp/AppDetailPage';
export type { TaskExecuteBody } from './hooks';
export { pathToEntityList } from './components/SchemaDrivenApp/AppDetailPage';
export { getStoredForm, STORED_FORM_KEY } from './components/SchemaDrivenApp';
export { ServiceSelector } from './components/ServiceSelector';
export type { ServiceSelectorProps } from './components/ServiceSelector';
export { SchemaSelector } from './components/SchemaSelector';
export type { SchemaSelectorProps } from './components/SchemaSelector';
export { TableSelector } from './components/TableSelector';
export type { TableSelectorProps } from './components/TableSelector';
export { FreeSoloSelect } from './components/FreeSoloSelect';
export type { FreeSoloSelectProps } from './components/FreeSoloSelect';
export { FreeSoloMultiSelect } from './components/FreeSoloMultiSelect';
export type { FreeSoloMultiSelectProps } from './components/FreeSoloMultiSelect';
export { HostSelector, StandaloneHostSelector } from './components/HostSelector';
export type { StandaloneHostSelectorProps } from './components/HostSelector';
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
  isTaskHistoryStatus,
  ChainDisplay,
  TaskFilesDialog,
} from './components/TaskHistoryTable';
export type {
  TaskHistoryTableProps,
  TaskHistoryEntry,
  TaskHistoryStatus,
  PaginatedTaskHistory,
  TaskFilesDialogProps,
} from './components/TaskHistoryTable';
export { SnippetExecutionAccordion } from './components/SnippetExecutionAccordion';
export type { SnippetExecutionAccordionProps } from './components/SnippetExecutionAccordion';
export { ChainBuilder } from './components/ChainBuilder';

export type { ChainBuilderProps, ChainValue, AvailableTask } from './components/ChainBuilder';
export { AlertOnFailField, ALERT_ON_FAIL_FIELD_NAME } from './components/AlertOnFailField';
export { ScheduledTasksPanel } from './components/ScheduledTasksPanel';
export {
  describePeriod,
  formatRelativeTime,
  formatAbsoluteTime,
  selectSchedule,
} from './components/ScheduledTasksPanel';
export type { PeriodDescription } from './components/ScheduledTasksPanel';
export { ScheduleCell } from './components/ScheduleCell';
export type { ScheduleCellProps } from './components/ScheduleCell';
export { ScheduleSummary } from './components/ScheduleSummary';
export type { ScheduleSummaryProps } from './components/ScheduleSummary';
export {
  useScheduledTasksForApp,
  useCreateScheduledTask,
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  type PeriodicTaskResponse,
  type PeriodicTaskCreate,
  type PeriodicTaskUpdate,
  type CrontabSchedule,
  type IntervalSchedule,
  type PeriodicTaskExecuteRequest,
} from './components/ScheduledTasksPanel/hooks';
export { default as DetailSyntaxHighlighter } from './components/SchemaDrivenApp/DetailSyntaxHighlighter';
export { detailSyntaxBlockSx } from './components/SchemaDrivenApp/detailSyntaxStyles';
export type { DetailSyntaxLanguage } from './components/SchemaDrivenApp/detailSyntaxStyles';

// Hooks
export { useServices, useSchemas, useTables, useHosts } from './hooks';
export type {
  ServiceOption,
  ServiceType,
  SchemaOption,
  TableOption,
  HostOption,
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
  useTaskHistoryByNames,
  useStopTaskHistory,
  useSnippetAppExecution,
  useSnippetAppSchema,
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
  UseSnippetAppExecutionOptions,
} from './hooks';

export {
  SNIPPET_FORM_RESERVED_FIELD_NAMES,
  buildSnippetExecutionFormPayload,
} from './utils/snippetFormSubmission';
export type { SnippetExecutionFormPayload } from './utils/snippetFormSubmission';

export type { SnippetExecutionRequest, SnippetExecutionResponse } from './types/snippetApp';

export { resolvePath } from './utils/resolvePath';

export { downloadBlob } from './utils/downloadBlob';

export {
  SNIPPETS_APPS_API_BASE,
  SNIPPET_APP_PER_SNIPPET_BASE,
  snippetAppApprovalPath,
  snippetAppDownloadPath,
  snippetAppExecutePath,
  snippetAppHistoryPath,
  snippetAppPreviewPath,
  snippetAppSchemaPath,
} from './snippetAppPaths';
