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

import { memo, useMemo } from 'react';
import { FormProvider, useForm, type SubmitHandler } from 'react-hook-form';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import Typography from '@mui/material/Typography';
import { FieldRenderer } from './fields';
import { useConditionalField } from './hooks/useConditionalField';
import { coerceFormValues } from './utils/validationMapper';
import type { FormSection, PluginField } from './types';

function fieldDefault(field: PluginField): unknown {
  switch (field.type) {
    case 'bool':
      return field.default ?? false;
    case 'integer':
    case 'float':
      return field.default ?? '';
    case 'multichoice':
      return field.default ?? [];
    case 'file':
      return undefined;
    case 'service':
    case 'schema':
    case 'table':
    case 'host':
      return field.default ?? '';
    default:
      return field.default ?? '';
  }
}

function flattenFields(sections: FormSection[]): PluginField[] {
  return sections.flatMap((s) => s.fields);
}

const ConditionalFieldSlot = memo(function ConditionalFieldSlot({ field }: { field: PluginField }) {
  const { isHidden, isRequired } = useConditionalField(field);

  if (isHidden) {
    return null;
  }

  const resolvedField = isRequired !== field.required ? { ...field, required: isRequired } : field;

  return (
    <Box sx={{ mb: 2 }}>
      <FieldRenderer field={resolvedField} />
    </Box>
  );
});

export interface SchemaFormRendererProps {
  sections: FormSection[];
  onSubmit: (data: Record<string, unknown>) => void;
  submitLabel?: string;
  loading?: boolean;
  defaultValues?: Record<string, unknown>;
  /** Server-side error to show above the form (e.g. API failure from the caller's mutation). */
  submitError?: string | null;
}

export function SchemaFormRenderer({
  sections,
  onSubmit,
  submitLabel = 'Run',
  loading = false,
  defaultValues,
  submitError,
}: SchemaFormRendererProps) {
  const allFields = useMemo(() => flattenFields(sections), [sections]);

  const formDefaults = useMemo(
    () =>
      allFields.reduce<Record<string, unknown>>((acc, field) => {
        acc[field.name] = defaultValues?.[field.name] ?? fieldDefault(field);
        return acc;
      }, {}),
    [allFields, defaultValues],
  );

  const methods = useForm<Record<string, unknown>>({ defaultValues: formDefaults });
  const { formState } = methods;
  const hasInlineErrors = Object.keys(formState.errors).length > 0;

  const handleSubmit: SubmitHandler<Record<string, unknown>> = (values) => {
    onSubmit(coerceFormValues(values, allFields));
  };

  return (
    <FormProvider {...methods}>
      <Box
        component="form"
        onSubmit={methods.handleSubmit(handleSubmit)}
        noValidate
        sx={{ maxWidth: 640 }}
      >
        {submitError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {submitError}
          </Alert>
        )}
        {hasInlineErrors && formState.isSubmitted && !submitError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Fix the highlighted fields before submitting.
          </Alert>
        )}

        {sections.map((section, idx) => (
          <Box key={section.title} component="fieldset" sx={{ border: 0, p: 0, mb: 3 }}>
            {idx > 0 && <Divider sx={{ mb: 2 }} />}
            <Typography component="legend" variant="h6" sx={{ mb: 1, px: 0 }}>
              {section.title}
            </Typography>
            {section.description && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                {section.description}
              </Typography>
            )}
            {section.fields.map((field) => (
              <ConditionalFieldSlot key={field.name} field={field} />
            ))}
          </Box>
        ))}

        <Button type="submit" variant="contained" size="large" disabled={loading} sx={{ mt: 1 }}>
          {submitLabel}
        </Button>
      </Box>
    </FormProvider>
  );
}
