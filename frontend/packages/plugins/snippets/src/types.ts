/**
 * Shared types for the snippets plugin frontend package.
 *
 * Mirrors the Pydantic API models defined in
 * `app/sep/plugins/snippets/models.py`.
 */

export interface SnippetResponse {
  filename: string;
  title: string;
  description: string;
  size: number;
  md5_digest: string;
  is_approved: boolean;
  approved_at: string | null;
  reason: string;
  requires_sudo: boolean;
  sudo_optional: boolean;
  sudo_default: boolean;
  interpreter: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface SnippetExecutionRequest {
  executor_host: string;
  sudo?: boolean;
  args?: Record<string, unknown>;
}

export interface SnippetExecutionResponse {
  task_name: string;
  task_id: number | null;
  snippet_filename: string;
}

export interface SnippetExecutionHistoryItem {
  task_id: number;
  status: string;
  created_at: string;
  created_by: string | null;
  available_files: string[];
}

export interface ScriptPreviewResponse {
  content: string;
  language: string;
  is_truncated: boolean;
}
