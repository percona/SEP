import { useForm } from 'react-hook-form';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import type { FormSection } from '@sep/api';
import { FieldRenderer } from './FieldRenderer';

interface SchemaFormRendererProps {
  sections: FormSection[];
  onSubmit: (data: Record<string, unknown>) => void;
  submitLabel?: string;
  loading?: boolean;
  defaultValues?: Record<string, unknown>;
}

export function SchemaFormRenderer({
  sections,
  onSubmit,
  submitLabel = 'Run',
  loading = false,
  defaultValues,
}: SchemaFormRendererProps) {
  const formDefaults = sections.reduce<Record<string, unknown>>((acc, section) => {
    section.fields.forEach((field) => {
      acc[field.name] = defaultValues?.[field.name] ?? field.default ?? '';
    });
    return acc;
  }, {});

  const { handleSubmit, control } = useForm({ defaultValues: formDefaults });

  return (
    <Box
      component="form"
      onSubmit={handleSubmit(onSubmit)}
      sx={{ maxWidth: 640 }}
    >
      {sections.map((section, idx) => (
        <Box key={section.title} sx={{ mb: 3 }}>
          {idx > 0 && <Divider sx={{ mb: 2 }} />}
          <Typography variant="h6" sx={{ mb: 1 }}>
            {section.title}
          </Typography>
          {section.description && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {section.description}
            </Typography>
          )}
          {section.fields.map((field) => (
            <FieldRenderer key={field.name} field={field} control={control} />
          ))}
        </Box>
      ))}

      <Button
        type="submit"
        variant="contained"
        size="large"
        disabled={loading}
        sx={{ mt: 1 }}
      >
        {submitLabel}
      </Button>
    </Box>
  );
}
