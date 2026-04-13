import type { Control } from 'react-hook-form';
import MenuItem from '@mui/material/MenuItem';
import {
  TextInput,
  SelectInput,
  SwitchInput,
} from '@percona/percona-ui';
import type { PluginField } from '@sep/api';
import { ServiceSelector } from '../ServiceSelector';
import { SchemaSelector } from '../SchemaSelector';
import { TableSelector } from '../TableSelector';

interface FieldRendererProps {
  field: PluginField;
  control: Control;
}

export function FieldRenderer({ field, control }: FieldRendererProps) {
  switch (field.type) {
    case 'string':
      return (
        <TextInput
          name={field.name}
          label={field.label}
          isRequired={field.required}
          control={control}
          textFieldProps={{
            placeholder: field.placeholder,
            helperText: field.description,
            fullWidth: true,
          }}
          controllerProps={{
            rules: {
              ...(field.required && { required: `${field.label} is required` }),
              ...(field.minLength && { minLength: { value: field.minLength, message: `Minimum ${field.minLength} characters` } }),
              ...(field.maxLength && { maxLength: { value: field.maxLength, message: `Maximum ${field.maxLength} characters` } }),
              ...(field.pattern && { pattern: { value: new RegExp(field.pattern), message: `Invalid format` } }),
            },
          }}
        />
      );

    case 'integer':
    case 'float':
      return (
        <TextInput
          name={field.name}
          label={field.label}
          isRequired={field.required}
          control={control}
          textFieldProps={{
            type: 'number',
            helperText: field.description,
            fullWidth: true,
            inputProps: {
              min: field.ge,
              max: field.le,
              step: field.step ?? (field.type === 'float' ? 0.1 : 1),
            },
          }}
          controllerProps={{
            rules: {
              ...(field.required && { required: `${field.label} is required` }),
              ...(field.ge != null && { min: { value: field.ge, message: `Minimum value is ${field.ge}` } }),
              ...(field.le != null && { max: { value: field.le, message: `Maximum value is ${field.le}` } }),
            },
          }}
        />
      );

    case 'bool':
      return (
        <SwitchInput
          name={field.name}
          label={field.label}
          labelCaption={field.description}
          control={control}
        />
      );

    case 'choice':
      return (
        <SelectInput
          name={field.name}
          label={field.label}
          isRequired={field.required}
          control={control}
          helperText={field.description}
          selectFieldProps={{ fullWidth: true }}
          controllerProps={{
            name: field.name,
            rules: {
              ...(field.required && { required: `${field.label} is required` }),
            },
          }}
        >
          {field.choices.map((choice) => {
            const label = typeof choice === 'string' ? choice : choice.label;
            const value = typeof choice === 'string' ? choice : choice.value;
            return (
              <MenuItem key={value} value={value}>
                {label}
              </MenuItem>
            );
          })}
        </SelectInput>
      );

    case 'textarea':
    case 'yaml':
      return (
        <TextInput
          name={field.name}
          label={field.label}
          isRequired={field.required}
          control={control}
          textFieldProps={{
            multiline: true,
            rows: field.rows ?? 4,
            placeholder: field.placeholder,
            helperText: field.description,
            fullWidth: true,
            ...(field.type === 'yaml' && {
              inputProps: { style: { fontFamily: "'Roboto Mono', monospace" } },
            }),
          }}
          controllerProps={{
            rules: {
              ...(field.required && { required: `${field.label} is required` }),
            },
          }}
        />
      );

    case 'datetime':
      return (
        <TextInput
          name={field.name}
          label={field.label}
          isRequired={field.required}
          control={control}
          textFieldProps={{
            type: 'datetime-local',
            helperText: field.description,
            fullWidth: true,
          }}
        />
      );

    case 'service':
      return (
        <ServiceSelector
          name={field.name}
          label={field.label}
          required={field.required}
          serviceTypes={field.serviceTypes}
          control={control}
        />
      );

    case 'schema':
      return (
        <SchemaSelector
          name={field.name}
          label={field.label}
          required={field.required}
          dependsOn={field.dependsOn}
          control={control}
        />
      );

    case 'table':
      return (
        <TableSelector
          name={field.name}
          label={field.label}
          required={field.required}
          dependsOn={field.dependsOn}
          control={control}
        />
      );

    case 'file':
      // TODO: implement file upload component
      return (
        <TextInput
          name={field.name}
          label={`${field.label} (file upload not yet supported)`}
          control={control}
          textFieldProps={{ disabled: true, fullWidth: true }}
        />
      );

    default:
      return null;
  }
}
