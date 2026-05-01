/**
 * Local type aliases for the plugin schema shape.
 *
 * Re-exports from `@sep/api` so field components and tests have a single
 * import surface. If the backend schema shape ever diverges from the api
 * package's contract, adapt here without touching every field file.
 */

export type {
  PluginSchema,
  PluginField,
  FormSection,
  StringField,
  IntegerField,
  FloatField,
  BoolField,
  ChoiceField,
  MultiChoiceField,
  TextAreaField,
  DateTimeField,
  FileField,
  YamlField,
  ServiceField,
  SchemaField,
  TableField,
  HostField,
  ScriptPreviewField,
} from '@sep/api';
