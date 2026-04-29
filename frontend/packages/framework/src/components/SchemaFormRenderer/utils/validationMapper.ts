import type { RegisterOptions } from 'react-hook-form';
import type { PluginField } from '../types';

export function buildValidationRules(field: PluginField): RegisterOptions {
  const rules: RegisterOptions = {};

  if (field.required) {
    rules.required = `${field.label} is required`;
  }

  switch (field.type) {
    case 'string': {
      if (field.minLength !== undefined) {
        rules.minLength = {
          value: field.minLength,
          message: `Minimum ${field.minLength} characters`,
        };
      }
      if (field.maxLength !== undefined) {
        rules.maxLength = {
          value: field.maxLength,
          message: `Maximum ${field.maxLength} characters`,
        };
      }
      if (field.pattern) {
        try {
          const compiled = new RegExp(field.pattern);
          rules.pattern = {
            value: compiled,
            message: `${field.label} does not match the required format`,
          };
        } catch {
          // Invalid regex from schema. Surface as a validate fn so the field
          // shows an error instead of the whole form crashing on render.
          rules.validate = () => `${field.label} has an invalid pattern in its schema`;
        }
      }
      break;
    }
    case 'integer':
    case 'float': {
      if (field.ge !== undefined) {
        rules.min = { value: field.ge, message: `Minimum value is ${field.ge}` };
      }
      if (field.le !== undefined) {
        rules.max = { value: field.le, message: `Maximum value is ${field.le}` };
      }
      break;
    }
    case 'textarea':
    case 'yaml': {
      if (field.type === 'textarea' || field.type === 'yaml') {
        // textarea/yaml share required-only rules today. Add length/pattern here if added later.
      }
      break;
    }
    case 'multichoice': {
      const { minItems, maxItems, label } = field;
      if (minItems !== undefined || maxItems !== undefined) {
        rules.validate = (value: unknown) => {
          const len = Array.isArray(value) ? value.length : 0;
          if (minItems !== undefined && len < minItems) {
            return `Select at least ${minItems} ${label.toLowerCase()}`;
          }
          if (maxItems !== undefined && len > maxItems) {
            return `Select at most ${maxItems} ${label.toLowerCase()}`;
          }
          return true;
        };
      }
      break;
    }
    default:
      break;
  }

  return rules;
}

/**
 * Coerce raw form values into the types the backend expects.
 *
 * react-hook-form's Controller does not expose setValueAs, so integer/float
 * fields reach the submit handler as strings. This walks the schema and
 * converts values based on their declared type. Empty strings become
 * undefined so optional numeric fields serialise cleanly.
 */
export function coerceFormValues(
  values: Record<string, unknown>,
  fields: PluginField[],
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...values };
  for (const field of fields) {
    const raw = out[field.name];
    if (field.type === 'integer' || field.type === 'float') {
      if (raw === '' || raw === undefined || raw === null) {
        out[field.name] = undefined;
        continue;
      }
      const num = field.type === 'integer' ? parseInt(String(raw), 10) : parseFloat(String(raw));
      out[field.name] = Number.isNaN(num) ? raw : num;
      continue;
    }
    if (field.type === 'service' || field.type === 'schema' || field.type === 'table') {
      // ServiceSelector et al. store the full `{id, name, …}` option object
      // in form state so the autocomplete can render the selected value.
      // Backend payloads expect the scalar id, so unwrap on submit.
      if (raw && typeof raw === 'object' && 'id' in (raw as Record<string, unknown>)) {
        const id = (raw as { id: unknown }).id;
        out[field.name] = id ?? undefined;
      } else if (raw === '' || raw === null) {
        out[field.name] = undefined;
      }
    }
  }
  return out;
}
