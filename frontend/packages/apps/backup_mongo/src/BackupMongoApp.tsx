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

import type { CSSProperties } from 'react';
import { SchemaDrivenApp } from '@sep/framework';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router';
import {
  BackupMongoTaskDetailExtras,
  getBackupMongoExecuteActions,
  getBackupMongoHistoryTaskNames,
} from './backupMongoTaskDetail';
import { backupMongoCreateRenderField } from './backupMongoCreateForm';
import {
  getRestoreMongoExecuteActions,
  getRestoreMongoHistoryTaskNames,
  RestoreMongoTaskDetailExtras,
} from './restoreMongoTaskDetail';
import {
  restoreMongoCreateForm,
  restoreMongoCreateRenderField,
  restoreMongoEditForm,
} from './restoreMongoCreateForm';
import { BACKUP_APP_NAME, MONGODB_BASE_PATH, RESTORE_APP_NAME } from './routes';

const BACKUP_DETAIL_SUPPRESS_KEYS = ['derived_tasks', 'latest_pbm_status'];
const RESTORE_DETAIL_SUPPRESS_KEYS = ['derived_tasks'];

const tabNavStyle: CSSProperties = {
  display: 'flex',
  gap: '1.5rem',
  marginBottom: '1.5rem',
  borderBottom: '1px solid rgba(0, 0, 0, 0.12)',
};

const tabLinkStyle: CSSProperties = {
  display: 'inline-block',
  padding: '0.75rem 0',
  textDecoration: 'none',
  color: 'inherit',
};

const tabLinkActiveStyle: CSSProperties = {
  ...tabLinkStyle,
  borderBottom: '2px solid #e74c3c',
  fontWeight: 600,
};

function MongoBackupTabs() {
  const { pathname } = useLocation();
  const isRestores = pathname.includes('/restores');

  return (
    <nav aria-label="MongoDB backup and restore" style={tabNavStyle}>
      <Link
        to={`${MONGODB_BASE_PATH}/backups`}
        style={isRestores ? tabLinkStyle : tabLinkActiveStyle}
        aria-current={isRestores ? undefined : 'page'}
      >
        Backups
      </Link>
      <Link
        to={`${MONGODB_BASE_PATH}/restores`}
        style={isRestores ? tabLinkActiveStyle : tabLinkStyle}
        aria-current={isRestores ? 'page' : undefined}
      >
        Restores
      </Link>
    </nav>
  );
}

export function BackupMongoApp() {
  return (
    <div>
      <MongoBackupTabs />
      <Routes>
        <Route index element={<Navigate to="backups" replace />} />
        <Route
          path="backups/*"
          element={
            <SchemaDrivenApp
              pluginName={BACKUP_APP_NAME}
              routeBase={`${MONGODB_BASE_PATH}/backups`}
              getTaskExecuteActions={getBackupMongoExecuteActions}
              getTaskHistoryNames={getBackupMongoHistoryTaskNames}
              suppressDetailKeys={BACKUP_DETAIL_SUPPRESS_KEYS}
              renderField={backupMongoCreateRenderField}
              renderTaskDetailChildren={({ task }) => <BackupMongoTaskDetailExtras task={task} />}
            />
          }
        />
        <Route
          path="restores/*"
          element={
            <SchemaDrivenApp
              pluginName={RESTORE_APP_NAME}
              routeBase={`${MONGODB_BASE_PATH}/restores`}
              getTaskExecuteActions={getRestoreMongoExecuteActions}
              getTaskHistoryNames={getRestoreMongoHistoryTaskNames}
              suppressDetailKeys={RESTORE_DETAIL_SUPPRESS_KEYS}
              renderField={restoreMongoCreateRenderField}
              renderCreateForm={restoreMongoCreateForm}
              renderEditForm={restoreMongoEditForm}
              renderTaskDetailChildren={({ task }) => <RestoreMongoTaskDetailExtras task={task} />}
            />
          }
        />
      </Routes>
    </div>
  );
}
