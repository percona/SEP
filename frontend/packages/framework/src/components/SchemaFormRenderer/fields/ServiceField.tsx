import { useFormContext } from 'react-hook-form';
import { ServiceSelector } from '../../ServiceSelector';
import type { ServiceField as ServiceFieldType } from '../types';

interface ServiceFieldProps {
  field: ServiceFieldType;
}

export function ServiceField({ field }: ServiceFieldProps) {
  const { control } = useFormContext();
  return (
    <ServiceSelector
      name={field.name}
      label={field.label}
      required={field.required}
      serviceTypes={field.serviceTypes}
      control={control}
    />
  );
}
