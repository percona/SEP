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
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { PluginCapabilities } from '@sep/api';
import { AlertOnFailField, ALERT_ON_FAIL_FIELD_NAME } from '../AlertOnFailField';
import { FieldRenderer } from './fields';
import { useConditionalField } from './hooks/useConditionalField';
import { useCardinalityRules } from './hooks/useCardinalityRules';
import { useFailRules } from './hooks/useFailRules';
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
  const resolvedField =
    Boolean(field.required) !== isRequired ? { ...field, required: isRequired } : field;

  return (
    <Box sx={{ mb: 2 }}>
      <FieldRenderer field={resolvedField} />
    </Box>
  );
});

interface SectionRendererProps {
  section: FormSection;
  idx: number;
  violations: Array<{ message: string }>;
}

const SectionRenderer = memo(function SectionRenderer({
  section,
  idx,
  violations,
}: SectionRendererProps) {
  const sectionContent = (
    <>
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
    </>
  );

  return (
    <Box component="fieldset" sx={{ border: 0, p: 0, mb: 3 }}>
      {idx > 0 && <Divider sx={{ mb: 2 }} />}
      {section.collapsible ? (
        <Accordion
          defaultExpanded={!section.collapsed_by_default}
          disableGutters
          slotProps={{ transition: { unmountOnExit: true } }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon />}
            sx={{
              pl: 2,
              pr: 1,
              minHeight: 48,
              '& .MuiAccordionSummary-content': { my: 1 },
            }}
          >
            <Typography component="legend" variant="subtitle1" sx={{ fontWeight: 600 }}>
              {section.title}
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, pl: 2 }}>{sectionContent}</AccordionDetails>
        </Accordion>
      ) : (
        <>
          <Typography component="legend" variant="h6" sx={{ mb: 1, px: 0 }}>
            {section.title}
          </Typography>
          {sectionContent}
        </>
      )}
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
  /** Plugin capabilities. When `alert_on_fail` is true, renders <AlertOnFailField> below the sections. */
  capabilities?: PluginCapabilities;
}

/** Inner form body — lives inside FormProvider so it can call useFormContext / useCardinalityRules. */
function SchemaFormBody({
  sections,
  onSubmit,
  submitLabel = 'Run',
  loading = false,
  submitError,
  capabilities,
}: SchemaFormRendererProps) {
  const { handleSubmit, formState } = useFormContext<Record<string, unknown>>();
  const allFields = useMemo(() => flattenFields(sections), [sections]);
  const beforeSubmitSections = useMemo(
    () => sections.filter((section) => !section.render_after_submit),
    [sections],
  );
  const afterSubmitSections = useMemo(
    () => sections.filter((section) => section.render_after_submit),
    [sections],
  );
  const cardinalityViolations = useCardinalityRules(sections);
  const failViolations = useFailRules(sections);

  // Merge cardinality and fail violations per section into a flat list for SectionRenderer.
  const violationsBySection = useMemo(() => {
    const map = new Map<FormSection, Array<{ message: string }>>();
    sections.forEach((section, i) => {
      map.set(section, [...(cardinalityViolations[i] ?? []), ...(failViolations[i] ?? [])]);
    });
    return map;
  }, [sections, cardinalityViolations, failViolations]);

  const hasSectionViolations = useMemo(
    () => [...violationsBySection.values()].some((vs) => vs.length > 0),
    [violationsBySection],
  );
  const hasInlineErrors = Object.keys(formState.errors).length > 0;

  const handleFormSubmit: SubmitHandler<Record<string, unknown>> = (values) => {
    if (hasSectionViolations) {
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

      {beforeSubmitSections.map((section, idx) => (
        <SectionRenderer
          key={`${section.title}-${idx}`}
          section={section}
          idx={idx}
          violations={violationsBySection.get(section) ?? []}
        />
      ))}

      {capabilities?.alert_on_fail && (
        <Box sx={{ mb: 2 }}>
          <AlertOnFailField />
        </Box>
      )}

      <Button type="submit" variant="contained" size="large" disabled={loading} sx={{ mt: 1 }}>
        {submitLabel}
      </Button>

      {afterSubmitSections.length > 0 ? (
        <Box sx={{ mt: 3 }}>
          {afterSubmitSections.map((section, idx) => (
            <SectionRenderer
              key={`${section.title}-after-${idx}`}
              section={section}
              idx={idx}
              violations={violationsBySection.get(section) ?? []}
            />
          ))}
        </Box>
      ) : null}
    </Box>
  );
}

export function SchemaFormRenderer(props: SchemaFormRendererProps) {
  const { sections, defaultValues, capabilities } = props;
  const allFields = useMemo(() => flattenFields(sections), [sections]);

  const formDefaults = useMemo(() => {
    const defaults = allFields.reduce<Record<string, unknown>>((acc, field) => {
      acc[field.name] = defaultValues?.[field.name] ?? fieldDefault(field);
      return acc;
    }, {});
    if (capabilities?.alert_on_fail) {
      // Capability-injected fields are not in allFields, so coerceFormValues leaves them
      // unchanged (extra keys pass through as-is via the initial spread). The value seeded
      // here must therefore already be the correct submit type — boolean for alert_on_fail.
      // If more capability fields are added, ensure they are pre-coerced at this point.
      defaults[ALERT_ON_FAIL_FIELD_NAME] = defaultValues?.[ALERT_ON_FAIL_FIELD_NAME] ?? false;
    }
    return defaults;
  }, [allFields, defaultValues, capabilities]);

  const methods = useForm<Record<string, unknown>>({ defaultValues: formDefaults });

  return (
    <FormProvider {...methods}>
      <SchemaFormBody {...props} />
    </FormProvider>
  );
}
