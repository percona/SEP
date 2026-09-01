/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { useMemo, type ReactNode } from 'react';
import { Link as RouterLink, useLocation, useNavigate } from 'react-router';
import Breadcrumbs from '@mui/material/Breadcrumbs';
import Box from '@mui/material/Box';
import MuiLink from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import { useAppEntityDetail, type ListView, type AppEntitySchema, type AppSchema } from '@sep/api';
import { SchemaListView } from '@sep/framework';
import { ConnectivityControl } from './ConnectivityControl';
import {
  inventoryMountPrefix,
  parseFlatInventoryRoute,
  parseNestedInventoryPath,
  pathThroughPairIndex,
  type NestedInventoryPair,
} from './inventoryNestedPaths';
import { SystemFactsPanel } from './SystemFactsPanel';

const ENTITY_NAMES = new Set(['nodes', 'services', 'schemas', 'tables']);

type Row = Record<string, unknown>;

// --- Breadcrumbs: record enrichment (flat detail URLs often omit nested parents) ---

function tableRecordNeedsServiceEnrichment(rec: Row | undefined): boolean {
  if (!rec) {
    return false;
  }
  const db = rec.database as Row | undefined;
  if (!db || typeof db !== 'object') {
    return false;
  }
  const svc = db.service as Row | undefined;
  if (!svc || typeof svc !== 'object') {
    return true;
  }
  const node = svc.node as Row | undefined;
  return !(node && typeof node === 'object');
}

function schemaRecordNeedsNodeEnrichment(rec: Row | undefined): boolean {
  if (!rec) {
    return false;
  }
  const svc = rec.service as Row | undefined;
  if (!svc || typeof svc !== 'object') {
    return false;
  }
  const node = svc.node as Row | undefined;
  return !(node && typeof node === 'object');
}

function serviceRecordNeedsNodeEnrichment(rec: Row | undefined): boolean {
  if (!rec) {
    return false;
  }
  const node = rec.node as Row | undefined;
  return !(node && typeof node === 'object');
}

function crumbLink(key: string, to: string, children: string) {
  return (
    <Typography
      key={key}
      component={RouterLink}
      to={to}
      variant="body2"
      color="primary"
      sx={{ textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
    >
      {children}
    </Typography>
  );
}

function crumbCurrent(key: string, label: string) {
  return (
    <Typography key={key} variant="body2" color="text.primary" fontWeight={600}>
      {label}
    </Typography>
  );
}

function labelsForNestedTrail(pairs: NestedInventoryPair[], record: Row | undefined): string[] {
  if (!record) {
    return pairs.map((p) => `${p.entity} #${p.id}`);
  }
  const last = pairs[pairs.length - 1]!.entity;
  if (last === 'nodes') {
    return [String(record.name ?? `Node #${pairs[0]!.id}`)];
  }
  if (last === 'services') {
    const node = record.node as Row | undefined;
    return [
      String(node?.name ?? `Node #${node?.id ?? pairs[0]!.id}`),
      String(record.name ?? `Service #${pairs[1]!.id}`),
    ];
  }
  if (last === 'schemas') {
    const svc = record.service as Row | undefined;
    const node = svc?.node as Row | undefined;
    return [
      String(node?.name ?? `Node #${node?.id ?? pairs[0]!.id}`),
      String(svc?.name ?? `Service #${svc?.id ?? pairs[1]!.id}`),
      String(record.name ?? `Schema #${pairs[2]!.id}`),
    ];
  }
  if (last === 'tables') {
    const db = record.database as Row | undefined;
    const svc = db?.service as Row | undefined;
    const node = svc?.node as Row | undefined;
    return [
      String(node?.name ?? `Node #${node?.id ?? pairs[0]!.id}`),
      String(svc?.name ?? `Service #${svc?.id ?? pairs[1]!.id}`),
      String(db?.name ?? `Schema #${db?.id ?? pairs[2]!.id}`),
      String(record.name ?? `Table #${pairs[3]!.id}`),
    ];
  }
  return pairs.map((p) => `${p.entity} #${p.id}`);
}

function crumbsFromNestedPath(
  prefix: string,
  pairs: NestedInventoryPair[],
  record: Row | undefined,
): ReactNode[] {
  const out: React.ReactNode[] = [];
  const nodesList = `${prefix}/nodes`;
  out.push(crumbLink('inv', nodesList, 'Inventory'));

  const labels = labelsForNestedTrail(pairs, record);
  for (let i = 0; i < pairs.length; i++) {
    const label = labels[i] ?? `${pairs[i]!.entity} #${pairs[i]!.id}`;
    const isLast = i === pairs.length - 1;
    if (isLast) {
      out.push(crumbCurrent(`leaf-${i}`, label));
      continue;
    }
    const to = pathThroughPairIndex(prefix, pairs, i + 1);
    out.push(crumbLink(`mid-${i}`, to, label));
  }
  return out;
}

/**
 * Name-based trail: Inventory → node → service → schema → (table), with nested URLs
 * ``/…/nodes/:id/services/:id/…`` when applicable.
 */
export function InventoryBreadcrumbs({ schema }: { schema: AppSchema }) {
  const location = useLocation();

  const prefix = useMemo(() => inventoryMountPrefix(location.pathname), [location.pathname]);

  // Flat read-only views (e.g. ``/inventory/target-hosts``) are not drill-down
  // entities, so they bypass the nested/flat entity parsing below and get a
  // simple ``Inventory → <view>`` trail.
  const isTargetHostsView = useMemo(
    () => Boolean(prefix) && location.pathname.replace(/\/+$/, '') === `${prefix}/target-hosts`,
    [location.pathname, prefix],
  );

  const nested = useMemo(
    () => (prefix ? parseNestedInventoryPath(location.pathname, prefix) : null),
    [location.pathname, prefix],
  );

  const flat = useMemo(
    () => (prefix ? parseFlatInventoryRoute(location.pathname, prefix) : {}),
    [location.pathname, prefix],
  );

  const entityName = nested?.entityName ?? flat.entityName;
  const id = nested?.id ?? flat.id;

  const detailEnabled = Boolean(prefix && entityName && id && ENTITY_NAMES.has(entityName));

  const { data: record } = useAppEntityDetail('inventory', entityName ?? '', id, undefined, {
    enabled: detailEnabled,
  });

  const tableCrumbServiceId = useMemo(() => {
    if (nested?.entityName === 'tables' && nested.pairs[1]?.entity === 'services') {
      return nested.pairs[1]!.id;
    }
    if (!nested && entityName === 'tables' && record) {
      const db = (record as Row).database as Row | undefined;
      const v = db?.service_id ?? (db?.service as Row | undefined)?.id;
      return v !== undefined && v !== null ? String(v) : undefined;
    }
    return undefined;
  }, [nested, entityName, record]);

  const fetchServiceForTableCrumbs = Boolean(
    prefix &&
    entityName === 'tables' &&
    Boolean(tableCrumbServiceId) &&
    (nested?.entityName === 'tables'
      ? !record || tableRecordNeedsServiceEnrichment(record as Row)
      : Boolean(record) && tableRecordNeedsServiceEnrichment(record as Row)),
  );

  const { data: tableServiceEnrichment } = useAppEntityDetail(
    'inventory',
    'services',
    tableCrumbServiceId,
    undefined,
    { enabled: fetchServiceForTableCrumbs },
  );

  const schemaBreadcrumbNodeId = useMemo(() => {
    if (nested?.entityName === 'schemas' && nested.pairs[0]?.entity === 'nodes') {
      return nested.pairs[0]!.id;
    }
    if (!nested && entityName === 'schemas' && record) {
      const svc = (record as Row).service as Row | undefined;
      const n = svc?.node_id ?? (svc?.node as Row | undefined)?.id;
      return n !== undefined && n !== null ? String(n) : undefined;
    }
    return undefined;
  }, [nested, entityName, record]);

  const fetchNodeForSchemaCrumbs = Boolean(
    prefix &&
    entityName === 'schemas' &&
    Boolean(schemaBreadcrumbNodeId) &&
    Boolean(record) &&
    schemaRecordNeedsNodeEnrichment(record as Row),
  );

  const { data: schemaNodeEnrichment } = useAppEntityDetail(
    'inventory',
    'nodes',
    schemaBreadcrumbNodeId,
    undefined,
    { enabled: fetchNodeForSchemaCrumbs },
  );

  const serviceBreadcrumbNodeId = useMemo(() => {
    if (nested?.entityName === 'services' && nested.pairs[0]?.entity === 'nodes') {
      return nested.pairs[0]!.id;
    }
    if (!nested && entityName === 'services' && record) {
      const n = (record as Row).node_id ?? ((record as Row).node as Row | undefined)?.id;
      return n !== undefined && n !== null ? String(n) : undefined;
    }
    return undefined;
  }, [nested, entityName, record]);

  const fetchNodeForServiceCrumbs = Boolean(
    prefix &&
    entityName === 'services' &&
    Boolean(serviceBreadcrumbNodeId) &&
    Boolean(record) &&
    serviceRecordNeedsNodeEnrichment(record as Row),
  );

  const { data: serviceNodeEnrichment } = useAppEntityDetail(
    'inventory',
    'nodes',
    serviceBreadcrumbNodeId,
    undefined,
    { enabled: fetchNodeForServiceCrumbs },
  );

  const breadcrumbDisplayRecord = useMemo(() => {
    if (!record) {
      return record;
    }

    let r = record as Row;

    if (entityName === 'services' && serviceNodeEnrichment) {
      r = { ...r, node: serviceNodeEnrichment as Row };
    }

    if (entityName === 'schemas' && schemaNodeEnrichment) {
      const svc = (r.service as Row | undefined) ?? {};
      r = {
        ...r,
        service: {
          ...svc,
          node: schemaNodeEnrichment as Row,
        },
      };
    }

    if (entityName === 'tables' && tableServiceEnrichment) {
      const db = (r.database as Row | undefined) ?? {};
      r = {
        ...r,
        database: {
          ...db,
          service: tableServiceEnrichment as Row,
        },
      };
    }

    return r;
  }, [entityName, record, schemaNodeEnrichment, serviceNodeEnrichment, tableServiceEnrichment]);

  const items = useMemo(() => {
    if (!prefix) {
      return [] as ReactNode[];
    }

    if (isTargetHostsView) {
      return [
        crumbLink('inv', `${prefix}/nodes`, 'Inventory'),
        crumbCurrent('target-hosts', 'Target hosts'),
      ];
    }

    if (nested) {
      return crumbsFromNestedPath(prefix, nested.pairs, breadcrumbDisplayRecord as Row | undefined);
    }

    const out: React.ReactNode[] = [];
    const nodesList = `${prefix}/nodes`;

    out.push(crumbLink('inv', nodesList, 'Inventory'));

    if (!entityName || !ENTITY_NAMES.has(entityName)) {
      return out;
    }

    if (!id) {
      const label =
        schema?.entities?.find((e: AppEntitySchema) => e.name === entityName)?.display_name ??
        entityName;
      out.push(crumbCurrent('list-entity', label));
      return out;
    }

    if (!breadcrumbDisplayRecord) {
      out.push(crumbCurrent('detail-fallback', `${entityName} #${id}`));
      return out;
    }

    const r = breadcrumbDisplayRecord as Row;

    if (entityName === 'nodes') {
      out.push(crumbCurrent('node', String(r.name ?? `Node #${id}`)));
      return out;
    }

    if (entityName === 'services') {
      const node = r.node as Row | undefined;
      if (node && node.id !== undefined) {
        out.push(
          crumbLink(
            'svc-node',
            `${prefix}/nodes/${node.id}`,
            String(node.name ?? `Node #${node.id}`),
          ),
        );
      }
      out.push(crumbCurrent('svc', String(r.name ?? `Service #${id}`)));
      return out;
    }

    if (entityName === 'schemas') {
      const svc = r.service as Row | undefined;
      const node = svc?.node as Row | undefined;
      const nid = node && node.id !== undefined ? node.id : undefined;
      const svid = svc && svc.id !== undefined ? svc.id : undefined;
      if (nid !== undefined) {
        out.push(
          crumbLink('sch-node', `${prefix}/nodes/${nid}`, String(node!.name ?? `Node #${nid}`)),
        );
      }
      if (svid !== undefined) {
        out.push(
          crumbLink(
            'sch-svc',
            `${prefix}/services/${svid}`,
            String(svc!.name ?? `Service #${svid}`),
          ),
        );
      }
      out.push(crumbCurrent('sch', String(r.name ?? `Schema #${id}`)));
      return out;
    }

    if (entityName === 'tables') {
      const db = r.database as Row | undefined;
      if (db && db.id !== undefined) {
        const svc = db.service as Row | undefined;
        const node = svc?.node as Row | undefined;
        const nid = node && node.id !== undefined ? node.id : undefined;
        const svid = svc && svc.id !== undefined ? svc.id : undefined;
        if (nid !== undefined) {
          out.push(
            crumbLink('tbl-node', `${prefix}/nodes/${nid}`, String(node!.name ?? `Node #${nid}`)),
          );
        }
        if (svid !== undefined) {
          out.push(
            crumbLink(
              'tbl-svc',
              `${prefix}/services/${svid}`,
              String(svc!.name ?? `Service #${svid}`),
            ),
          );
        }
        out.push(
          crumbLink('tbl-sch', `${prefix}/schemas/${db.id}`, String(db.name ?? `Schema #${db.id}`)),
        );
      }
      out.push(crumbCurrent('tbl', String(r.name ?? `Table #${id}`)));
      return out;
    }

    return out;
  }, [
    breadcrumbDisplayRecord,
    entityName,
    id,
    isTargetHostsView,
    nested,
    prefix,
    schema?.entities,
  ]);

  if (items.length === 0) {
    return null;
  }

  return (
    <Breadcrumbs sx={{ mb: 2 }} aria-label="Inventory breadcrumb">
      {items}
    </Breadcrumbs>
  );
}

// --- Detail page: nested lists + parent links ---

function isRecordArray(v: unknown): v is Row[] {
  return (
    Array.isArray(v) && v.every((x) => x !== null && typeof x === 'object' && !Array.isArray(x))
  );
}

function listViewFor(schema: AppSchema, entityName: string): ListView | undefined {
  return schema.entities?.find((e: AppEntitySchema) => e.name === entityName)?.list_view;
}

function isIdLike(v: unknown): v is string | number {
  return typeof v === 'string' || typeof v === 'number';
}

/**
 * Build a child URL that preserves the current nested drill-down context. If the
 * current path is already nested, append ``childEntity/childId`` to it; otherwise
 * derive the parent chain from ``record`` and fall back to a flat URL only when
 * the chain cannot be reconstructed.
 */
function nestedChildHref(
  prefix: string,
  pathname: string,
  parentEntityName: string,
  parentRecord: Row,
  childEntityName: string,
  childId: string | number,
): string {
  const nested = parseNestedInventoryPath(pathname, prefix);
  if (nested) {
    const trail = nested.pairs.map((p) => `${p.entity}/${p.id}`).join('/');
    return `${prefix}/${trail}/${childEntityName}/${childId}`;
  }
  const pid = parentRecord.id;
  if (parentEntityName === 'nodes' && isIdLike(pid)) {
    return `${prefix}/nodes/${pid}/${childEntityName}/${childId}`;
  }
  if (parentEntityName === 'services' && isIdLike(pid)) {
    const node = parentRecord.node as Row | undefined;
    if (node && isIdLike(node.id)) {
      return `${prefix}/nodes/${node.id}/services/${pid}/${childEntityName}/${childId}`;
    }
  }
  if (parentEntityName === 'schemas' && isIdLike(pid)) {
    const svc = parentRecord.service as Row | undefined;
    const node = svc?.node as Row | undefined;
    if (svc && isIdLike(svc.id) && node && isIdLike(node.id)) {
      return `${prefix}/nodes/${node.id}/services/${svc.id}/schemas/${pid}/${childEntityName}/${childId}`;
    }
  }
  return `${prefix}/${childEntityName}/${childId}`;
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
 * Legacy-style drill-down (node → services → schemas → tables) on entity detail pages.
 */
export function renderInventoryDetailChildren({
  entityName,
  record,
  schema,
  pathname,
}: {
  entityName: string;
  record: Row;
  schema: AppSchema;
  pathname: string;
}): ReactNode {
  const prefix = inventoryMountPrefix(pathname);
  const blocks: ReactNode[] = [];

  if (
    (entityName === 'nodes' || entityName === 'services') &&
    isIdLike(record.id) &&
    /^\d+$/.test(String(record.id))
  ) {
    // Gate on the same numeric check the hook uses: a non-numeric id would
    // disable the query yet still render a misleading empty state.
    blocks.push(<SystemFactsPanel key="system-facts" entity={entityName} id={record.id} />);
  }

  if (entityName === 'services' && isIdLike(record.id) && /^\d+$/.test(String(record.id))) {
    blocks.push(
      <ConnectivityControl key="connectivity" serviceId={record.id} serviceType={record.type} />,
    );
  }

  if (entityName === 'nodes' && isRecordArray(record.services) && prefix) {
    const lv = listViewFor(schema, 'services');
    if (lv) {
      blocks.push(
        <NestedListSection
          key="services"
          title="Services on this node"
          listView={lv}
          rows={record.services}
          rowHref={(row) =>
            isIdLike(row.id)
              ? nestedChildHref(prefix, pathname, 'nodes', record, 'services', row.id)
              : `${prefix}/services/${row.id}`
          }
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
          rowHref={(row) =>
            isIdLike(row.id)
              ? nestedChildHref(prefix, pathname, 'services', record, 'schemas', row.id)
              : `${prefix}/schemas/${row.id}`
          }
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
          rowHref={(row) =>
            isIdLike(row.id)
              ? nestedChildHref(prefix, pathname, 'schemas', record, 'tables', row.id)
              : `${prefix}/tables/${row.id}`
          }
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
