// API client
export { apiClient, setTokenProvider, setOnUnauthorized } from './client';

// Query client
export { createQueryClient, defaultQueryClientConfig } from './queryClient';

// Errors
export { ApiError, normalizeAxiosError } from './errors';
export type { ApiErrorDetails, ApiErrorKind } from './errors';

// Auth
export { postLogin, postRefresh, fetchCurrentUser } from './auth';

// Types
export type { PaginatedResponse, ApiErrorResponse, OAuthTokenResponse, User } from './types/api';

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
