import type { PluginSchema } from '@sep/api';
import {
  InventoryBreadcrumbs,
  SchemaDrivenPlugin,
  renderInventoryDetailChildren,
} from '@sep/framework';

export interface InventoryPluginProps {
  /** Optional mock schema for Storybook / offline tests. */
  mockSchema?: PluginSchema;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
}

const INVENTORY_DETAIL_SUPPRESS_KEYS = [
  'services',
  'schemas',
  'tables',
  'node',
  'service',
  'database',
];

/**
 * Inventory plugin — browse nodes, services, schemas, and tables with the same drill-down
 * as the legacy UI (node → services → schemas → tables), without create/edit/delete in React.
 */
export function InventoryPlugin({ mockSchema, mockEntityItems }: InventoryPluginProps) {
  return (
    <>
      <InventoryBreadcrumbs mockSchema={mockSchema} />
      <SchemaDrivenPlugin
        pluginName="inventory"
        mockSchema={mockSchema}
        mockEntityItems={mockEntityItems}
        browseOnly
        hideEntityTabs
        inventoryNestedPaths
        suppressDetailKeys={INVENTORY_DETAIL_SUPPRESS_KEYS}
        renderEntityDetailChildren={renderInventoryDetailChildren}
      />
    </>
  );
}
