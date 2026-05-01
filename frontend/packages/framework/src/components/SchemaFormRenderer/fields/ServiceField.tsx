import { ServiceSelector } from '../../ServiceSelector';
import type { ServiceType } from '../../../hooks/useServices';
import type { ServiceField as ServiceFieldType } from '../types';

interface ServiceFieldProps {
  field: ServiceFieldType;
}

export function ServiceField({ field }: ServiceFieldProps) {
  return (
    <ServiceSelector
      name={field.name}
      label={field.label}
      required={field.required}
      serviceTypes={field.serviceTypes as readonly ServiceType[]}
    />
  );
}
