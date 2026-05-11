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

/// <reference path="./vite-env.d.ts" />

// API client
export {
  apiClient,
  emitUnauthorized,
  getToken,
  refreshAccessToken,
  setTokenProvider,
  setOnUnauthorized,
  setOnRefreshed,
} from './client';

// Query client
export { createQueryClient, defaultQueryClientConfig } from './queryClient';

// Errors
export { ApiError, normalizeAxiosError } from './errors';
export type { ApiErrorDetails, ApiErrorKind } from './errors';

// Auth
export { postLogin, postRefresh, postLogout, fetchCurrentUser } from './auth';

// Types (re-exported from generated OpenAPI schemas)
export type { OAuthTokenResponse, SPAOAuthTokenResponse, User } from './types/api';

// Generated OpenAPI type surfaces — use for typed openapi-fetch clients
// and for type-only imports in plugins and framework code.
export type {
  paths as MainPaths,
  components as MainComponents,
  operations as MainOperations,
} from './generated/main';
export type {
  paths as InventoryPaths,
  components as InventoryComponents,
} from './generated/inventory';
export type { paths as TasksPaths, components as TasksComponents } from './generated/tasks';
export type { paths as SepPaths, components as SepComponents } from './generated/sep';

// Typed request clients (openapi-fetch wrappers sharing interceptors with apiClient)
export { mainApi, inventoryApi, tasksApi, sepApi } from './typed-client';

export type {
  PluginSchema,
  PluginEntitySchema,
  PluginField,
  FormSection,
  ListColumn,
  ListView,
  PluginCapabilities,
  StringField,
  IntegerField,
  FloatField,
  BoolField,
  ChoiceField,
  MultiChoiceField,
  TextAreaField,
  DateTimeField,
  FileField,
  YamlField,
  ServiceField,
  SchemaField,
  TableField,
  HostField,
  ScriptPreviewField,
} from './types/plugin-schema';

// Hooks
export {
  useCurrentUser,
  usePluginSchema,
  usePluginTasks,
  usePluginTask,
  useCreatePluginTask,
  usePluginEntityList,
  usePluginEntityDetail,
  useCreatePluginEntity,
  useUpdatePluginEntity,
  useDeletePluginEntity,
  useDeletePluginTask,
  useAlertConfig,
  ALERT_CONFIG_QUERY_KEY,
} from './hooks';
export type { AlertConfig } from './hooks';
