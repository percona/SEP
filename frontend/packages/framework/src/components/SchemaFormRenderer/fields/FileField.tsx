import { useFormContext } from 'react-hook-form';
import { FileInput } from '@percona/percona-ui';
import type { FileField as FileFieldType } from '../types';

interface FileFieldProps {
  field: FileFieldType;
}

export function FileField({ field }: FileFieldProps) {
  const { control } = useFormContext();
  return (
    <FileInput
      name={field.name}
      label={field.label}
      control={control}
      textFieldProps={{
        helperText: field.description,
        fullWidth: true,
        required: field.required,
      }}
      fileInputProps={{
        accept: field.accept?.join(','),
      }}
    />
  );
}
