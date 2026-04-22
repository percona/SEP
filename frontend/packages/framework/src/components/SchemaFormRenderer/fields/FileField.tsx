import { Controller, useFormContext } from 'react-hook-form';
import { IconButton, InputAdornment, TextField } from '@mui/material';
import AttachFileIcon from '@mui/icons-material/AttachFile';
import type { FileField as FileFieldType } from '../types';
import { buildValidationRules } from '../utils/validationMapper';

interface FileFieldProps {
  field: FileFieldType;
}

// percona-ui's FileInput owns its own internal Controller and exposes no
// controllerProps, so we cannot attach react-hook-form rules to it. The form
// also sets noValidate, which suppresses the native required attribute. To
// make required (and any future file rules) actually block submission, we
// render the Controller ourselves here.
export function FileField({ field }: FileFieldProps) {
  const { control } = useFormContext();
  const rules = buildValidationRules(field);
  const inputId = `file-input-${field.name}`;

  return (
    <Controller
      name={field.name}
      control={control}
      rules={rules}
      render={({ field: rhf, fieldState: { error } }) => (
        <TextField
          label={field.label}
          required={field.required}
          fullWidth
          size="small"
          value={rhf.value instanceof File ? rhf.value.name : ''}
          error={!!error}
          helperText={error ? error.message : field.description}
          slotProps={{
            input: {
              readOnly: true,
              endAdornment: (
                <InputAdornment position="end">
                  <IconButton component="label" htmlFor={inputId} edge="end">
                    <AttachFileIcon fontSize="small" />
                    <input
                      id={inputId}
                      type="file"
                      hidden
                      accept={field.accept?.join(',')}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        rhf.onChange(file ?? undefined);
                      }}
                      onBlur={rhf.onBlur}
                    />
                  </IconButton>
                </InputAdornment>
              ),
            },
          }}
        />
      )}
    />
  );
}
