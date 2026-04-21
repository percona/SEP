import { useEffect, useRef } from 'react';
import { useFormContext, useWatch } from 'react-hook-form';

interface UseCascadingFieldArgs {
  /** Name of the field owning the cascade (the downstream field). */
  fieldName: string;
  /** Name of the upstream field to observe, or undefined if this field has no dependency. */
  dependsOn?: string;
}

interface UseCascadingFieldResult<T> {
  /** Current value of the upstream field, or undefined if no dependency is declared. */
  upstreamValue: T | undefined;
  /** True once the upstream value is set (or if there is no dependency). */
  ready: boolean;
}

/**
 * Observe an upstream field and reset this field when the upstream changes.
 *
 * Domain selectors (schema -> service, table -> schema) need to clear their
 * current value when the parent changes so stale selections cannot submit.
 * Consumers still own option fetching; the hook only tracks the dependency.
 */
export function useCascadingField<T = unknown>({
  fieldName,
  dependsOn,
}: UseCascadingFieldArgs): UseCascadingFieldResult<T> {
  const { control, setValue } = useFormContext();
  const upstreamValue = useWatch({ control, name: dependsOn ?? '__noop__' }) as T | undefined;
  const previousRef = useRef<T | undefined>(dependsOn ? upstreamValue : undefined);
  const didMountRef = useRef(false);

  useEffect(() => {
    if (!dependsOn) {
      return;
    }
    if (!didMountRef.current) {
      didMountRef.current = true;
      previousRef.current = upstreamValue;
      return;
    }
    if (previousRef.current !== upstreamValue) {
      setValue(fieldName, undefined, { shouldValidate: false, shouldDirty: false });
      previousRef.current = upstreamValue;
    }
  }, [upstreamValue, fieldName, dependsOn, setValue]);

  return {
    upstreamValue: dependsOn ? upstreamValue : undefined,
    ready: dependsOn ? upstreamValue !== undefined && upstreamValue !== null : true,
  };
}
