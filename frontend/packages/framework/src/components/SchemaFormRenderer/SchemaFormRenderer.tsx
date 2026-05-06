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
import { FormProvider, useForm, useFormContext, type SubmitHandler } from 'react-hook-form';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import Typography from '@mui/material/Typography';
import { FieldRenderer } from './fields';
import { useConditionalField } from './hooks/useConditionalField';
import { useCardinalityRules, type CardinalityViolation } from './hooks/useCardinalityRules';
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

  // Clone the field with the resolved required flag so FieldRenderer passes it
  // to register(). RHF's register() is idempotent — re-calling it on each
  // render updates the validation rules in place, so the required constraint
  // stays in sync with gate state without a separate validate callback.
  const resolvedField = isRequired !== field.required ? { ...field, required: isRequired } : field;

  return (
    <Box sx={{ mb: 2 }}>
      <FieldRenderer field={resolvedField} />
    </Box>
  );
});

interface SectionRendererProps {
  section: FormSection;
  idx: number;
  violations: CardinalityViolation[];
}

const SectionRenderer = memo(function SectionRenderer({
  section,
  idx,
  violations,
}: SectionRendererProps) {
  return (
    <Box component="fieldset" sx={{ border: 0, p: 0, mb: 3 }}>
      {idx > 0 && <Divider sx={{ mb: 2 }} />}
      <Typography component="legend" variant="h6" sx={{ mb: 1, px: 0 }}>
        {section.title}
      </Typography>
      {section.description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {section.description}
        </Typography>
      )}
      {violations.map((v, i) => (
        <Alert key={i} severity="error" sx={{ mb: 1 }}>
          {v.message}
        </Alert>
      ))}
      {section.fields.map((field) => (
        <ConditionalFieldSlot key={field.name} field={field} />
      ))}
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

/** Inner form body — lives inside FormProvider so it can call useFormContext / useCardinalityRules. */
function SchemaFormBody({
  sections,
  onSubmit,
  submitLabel = 'Run',
  loading = false,
  submitError,
}: SchemaFormRendererProps) {
  const { handleSubmit, formState } = useFormContext<Record<string, unknown>>();
  const allFields = useMemo(() => flattenFields(sections), [sections]);
  const violationsPerSection = useCardinalityRules(sections);

  const hasCardinalityViolations = violationsPerSection.some((vs) => vs.length > 0);
  const hasInlineErrors = Object.keys(formState.errors).length > 0;

  const handleFormSubmit: SubmitHandler<Record<string, unknown>> = (values) => {
    if (hasCardinalityViolations) {
      return;
    }
    onSubmit(coerceFormValues(values, allFields));
  };

  return (
    <Box
      component="form"
      onSubmit={handleSubmit(handleFormSubmit)}
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
        <SectionRenderer
          key={section.title}
          section={section}
          idx={idx}
          violations={violationsPerSection[idx] ?? []}
        />
      ))}

      <Button type="submit" variant="contained" size="large" disabled={loading} sx={{ mt: 1 }}>
        {submitLabel}
      </Button>
    </Box>
  );
}

export function SchemaFormRenderer(props: SchemaFormRendererProps) {
  const { sections, defaultValues } = props;
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

  return (
    <FormProvider {...methods}>
      <SchemaFormBody {...props} />
    </FormProvider>
  );
}
