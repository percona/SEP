import { SchemaDrivenPlugin } from '@sep/framework';
import { checksumsSchema } from './schema';
import { mockChecksumTasks } from './mock-data';

/**
 * Checksums plugin — zero custom UI code.
 *
 * The SchemaDrivenPlugin reads the schema and auto-generates:
 * - List page with sortable/filterable table
 * - Create page with auto-generated form
 * - Detail page showing task data
 *
 * Once the backend serves the schema at /api/plugins/checksums/schema,
 * remove mockSchema and mockTasks — the framework fetches everything.
 */
export function ChecksumsPlugin() {
  return (
    <SchemaDrivenPlugin
      pluginName="checksums"
      mockSchema={checksumsSchema}
      mockTasks={[...mockChecksumTasks]}
    />
  );
}
