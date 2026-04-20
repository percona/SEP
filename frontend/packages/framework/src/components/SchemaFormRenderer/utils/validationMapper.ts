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
        rules.pattern = {
          value: new RegExp(field.pattern),
          message: `${field.label} does not match the required format`,
        };
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
    }
  }
  return out;
}
