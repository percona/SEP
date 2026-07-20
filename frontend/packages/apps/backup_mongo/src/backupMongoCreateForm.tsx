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

import { useEffect, useRef, type ReactNode } from 'react';
import { useFormContext, useWatch } from 'react-hook-form';
import type { RenderFieldOverride } from '@sep/framework';
import {
  isAutoMongoBackupTaskName,
  suggestMongoBackupTaskName,
} from './suggestMongoBackupTaskName';

function serviceDisplayName(value: unknown): string | undefined {
  if (value && typeof value === 'object' && 'name' in value) {
    const name = (value as { name: unknown }).name;
    return typeof name === 'string' ? name : undefined;
  }
  return undefined;
}

function serviceResetKey(value: unknown): string {
  if (value && typeof value === 'object' && 'id' in value) {
    return `id:${String((value as { id: unknown }).id ?? 'none')}`;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return `id:${value}`;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    return `raw:${value.trim()}`;
  }
  return 'id:none';
}

/**
 * Keep ``task_name`` filled with a service+timestamp suggestion while the user
 * has not edited it. Mounted via the create-form ``renderField`` override so it
 * runs inside SchemaFormRenderer's FormProvider.
 */
function SuggestedTaskNameEffect({ schemaDefault }: { schemaDefault?: string }) {
  const { setValue, getValues } = useFormContext();
  const service = useWatch({ name: 'service_id' });
  const resetKey = serviceResetKey(service);
  const autoRef = useRef<string | undefined>(undefined);
  const prevServiceKeyRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    const isFirst = prevServiceKeyRef.current === undefined;
    const serviceChanged =
      prevServiceKeyRef.current !== undefined && prevServiceKeyRef.current !== resetKey;
    prevServiceKeyRef.current = resetKey;

    // Only act on mount or when the upstream service changes — avoid minting a
    // new timestamp on every incidental re-render.
    if (!isFirst && !serviceChanged) {
      return;
    }

    const current = String(getValues('task_name') ?? '');
    if (!isAutoMongoBackupTaskName(current, autoRef.current, schemaDefault)) {
      return;
    }

    const next = suggestMongoBackupTaskName(serviceDisplayName(service));
    setValue('task_name', next, { shouldDirty: false, shouldValidate: false });
    autoRef.current = next;
  }, [resetKey, schemaDefault, service, setValue, getValues]);

  return null;
}

/**
 * Create-form field override: suggest a task name for ``task_name``, leave
 * every other field to the framework default widget.
 */
export const backupMongoCreateRenderField: RenderFieldOverride = ({
  field,
  renderDefault,
}): ReactNode => {
  if (field.name !== 'task_name') {
    return renderDefault();
  }
  const schemaDefault = typeof field.default === 'string' ? field.default : undefined;

  return (
    <>
      <SuggestedTaskNameEffect schemaDefault={schemaDefault} />
      {renderDefault()}
    </>
  );
};
