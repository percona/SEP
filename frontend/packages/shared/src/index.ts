/**
 * @sep/shared — Tiny constants & utility package.
 *
 * API client, auth, types, and schema components have moved to:
 *   - @sep/api      — client, auth, types, hooks
 *   - @sep/framework — SchemaFormRenderer, SchemaDrivenPlugin, etc.
 *
 * This package now only holds cross-cutting constants and tiny utilities
 * shared across all packages (e.g., route paths, feature flags).
 */

// ── Route paths (single source of truth for navigation + router) ──────
export const ROUTES = {
  dashboard: '/',
  login: '/login',
  inventory: '/inventory',
  tasks: '/tasks',
  snippets: '/snippets',
  alertTemplates: '/alerts/templates',
  alertTroubleshooting: '/alerts/troubleshooting',
  schemaAlters: '/schema-change/alters',
  schemaChecksums: '/schema-change/checksums',
  backupsMysql: '/backups/mysql',
  backupsMongodb: '/backups/mongodb',
  backupsPostgresql: '/backups/postgresql',
  archive: '/archive',
  reports: '/reports',
  settings: '/settings',
} as const;

// ── App-wide constants ────────────────────────────────────────────────
export const APP_NAME = 'Services Enablement Platform';
export const APP_SHORT_NAME = 'SEP';
