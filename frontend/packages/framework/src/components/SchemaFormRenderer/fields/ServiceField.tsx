import { useFormContext } from 'react-hook-form';
import { ServiceSelector } from '../../ServiceSelector';
import type { ServiceType } from '../../../hooks/useServices';
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
      serviceTypes={field.serviceTypes as readonly ServiceType[]}
      control={control}
    />
  );
}
