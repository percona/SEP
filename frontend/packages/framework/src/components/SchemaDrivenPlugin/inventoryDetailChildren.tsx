import type { ReactNode } from 'react';
import { useNavigate, Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import MuiLink from '@mui/material/Link';
import type { ListView, PluginEntitySchema, PluginSchema } from '@sep/api';
import { SchemaListView } from '../SchemaListView';
import { inventoryMountPrefix } from './inventoryNestedPaths';

type Row = Record<string, unknown>;

function isRecordArray(v: unknown): v is Row[] {
  return (
    Array.isArray(v) && v.every((x) => x !== null && typeof x === 'object' && !Array.isArray(x))
  );
}

function listViewFor(schema: PluginSchema, entityName: string): ListView | undefined {
  return schema.entities?.find((e: PluginEntitySchema) => e.name === entityName)?.listView;
}

/**
 * URL prefix ending at the ``inventory`` segment (e.g. ``/inventory`` or ``/schema-change/inventory``).
 * @deprecated Prefer ``inventoryMountPrefix`` from ``inventoryNestedPaths`` for nested inventory URLs.
 */
export function inventoryPluginBasePath(pathname: string, entityName: string): string {
  void entityName;
  return inventoryMountPrefix(pathname);
}

function NestedListSection({
  title,
  listView,
  rows,
  rowHref,
}: {
  title: string;
  listView: ListView;
  rows: Row[];
  rowHref: (row: Row) => string;
}) {
  const navigate = useNavigate();

  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        {title}
      </Typography>
      <SchemaListView
        listView={listView}
        data={rows}
        onRowClick={rows.length > 0 ? (row) => navigate(rowHref(row as Row)) : undefined}
      />
    </Box>
  );
}

function ParentLink({ label, to, name }: { label: string; to: string; name?: string }) {
  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body1">
        <MuiLink component={RouterLink} to={to} underline="hover">
          {name ?? to}
        </MuiLink>
      </Typography>
    </Box>
  );
}

/**
 * Renders legacy-style drill-down (node → services → schemas → tables) using the same
 * ``MaterialReactTable`` list views as the top-level inventory tabs.
 *
 * Uses absolute paths derived from ``location.pathname`` so navigation stays correct
 * when the plugin is mounted under splat routes (e.g. ``/inventory/*``).
 */
export function renderInventoryDetailChildren({
  entityName,
  record,
  schema,
  pathname,
}: {
  entityName: string;
  record: Row;
  schema: PluginSchema;
  pathname: string;
}): ReactNode {
  const prefix = inventoryMountPrefix(pathname);
  const blocks: ReactNode[] = [];

  if (entityName === 'nodes' && isRecordArray(record.services) && prefix) {
    const lv = listViewFor(schema, 'services');
    if (lv) {
      blocks.push(
        <NestedListSection
          key="services"
          title="Services on this node"
          listView={lv}
          rows={record.services}
          rowHref={(row) => `${prefix}/services/${row.id}`}
        />,
      );
    }
  }

  if (entityName === 'services' && isRecordArray(record.schemas) && prefix) {
    const lv = listViewFor(schema, 'schemas');
    if (lv) {
      blocks.push(
        <NestedListSection
          key="schemas"
          title="Schemas in this service"
          listView={lv}
          rows={record.schemas}
          rowHref={(row) => `${prefix}/schemas/${row.id}`}
        />,
      );
    }
  }

  if (entityName === 'schemas' && record.service && typeof record.service === 'object' && prefix) {
    const svc = record.service as Row;
    const node = svc.node as Row | undefined;
    const sid = svc.id;
    if (
      (typeof sid === 'number' || typeof sid === 'string') &&
      node &&
      (typeof node.id === 'number' || typeof node.id === 'string')
    ) {
      blocks.push(
        <ParentLink
          key="service"
          label="Service"
          to={`${prefix}/nodes/${node.id}/services/${sid}`}
          name={typeof svc.name === 'string' ? (svc.name as string) : `Service #${sid}`}
        />,
      );
    }
  }

  if (entityName === 'schemas' && isRecordArray(record.tables) && prefix) {
    const lv = listViewFor(schema, 'tables');
    if (lv) {
      blocks.push(
        <NestedListSection
          key="tables"
          title="Tables in this schema"
          listView={lv}
          rows={record.tables}
          rowHref={(row) => `${prefix}/tables/${row.id}`}
        />,
      );
    }
  }

  if (entityName === 'tables' && record.database && typeof record.database === 'object' && prefix) {
    const sch = record.database as Row;
    const sid = sch.id;
    const svc = sch.service as Row | undefined;
    const node = svc?.node as Row | undefined;
    if (
      (typeof sid === 'number' || typeof sid === 'string') &&
      svc &&
      (typeof svc.id === 'number' || typeof svc.id === 'string') &&
      node &&
      (typeof node.id === 'number' || typeof node.id === 'string')
    ) {
      blocks.push(
        <ParentLink
          key="schema"
          label="Schema"
          to={`${prefix}/nodes/${node.id}/services/${svc.id}/schemas/${sid}`}
          name={typeof sch.name === 'string' ? (sch.name as string) : `Schema #${sid}`}
        />,
      );
    }
  }

  if (blocks.length === 0) {
    return null;
  }

  return <>{blocks}</>;
}
