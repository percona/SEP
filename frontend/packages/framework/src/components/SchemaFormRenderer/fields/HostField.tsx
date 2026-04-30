import { HostSelector } from '../../HostSelector';
import type { HostField as HostFieldType } from '../types';

interface HostFieldProps {
  field: HostFieldType;
}

export function HostField({ field }: HostFieldProps) {
  return <HostSelector name={field.name} label={field.label} required={field.required} />;
}
