// API client
export { apiClient, setTokenProvider, setOnUnauthorized } from './client';

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

// Sample typed hook (demonstrates the full codegen → openapi-fetch → useQuery pattern)
export { useCurrentUser } from './hooks/useCurrentUser';

export type {
  PluginSchema,
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
  TextAreaField,
  DateTimeField,
  FileField,
  YamlField,
  ServiceField,
  SchemaField,
  TableField,
} from './types/plugin-schema';

// Hooks
export { usePluginSchema, usePluginTasks, usePluginTask, useCreatePluginTask } from './hooks';
