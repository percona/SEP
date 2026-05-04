import { useMemo, type ReactNode } from 'react';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import Breadcrumbs from '@mui/material/Breadcrumbs';
import Typography from '@mui/material/Typography';
import {
  usePluginEntityDetail,
  usePluginSchema,
  type PluginEntitySchema,
  type PluginSchema,
} from '@sep/api';
import {
  inventoryMountPrefix,
  parseFlatInventoryRoute,
  parseNestedInventoryPath,
  pathThroughPairIndex,
  type NestedInventoryPair,
} from './inventoryNestedPaths';

const ENTITY_NAMES = new Set(['nodes', 'services', 'schemas', 'tables']);

type Row = Record<string, unknown>;

/** Table detail JSON often omits ``database.service`` unless the API eager-loads it. */
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

/** Schema detail may include ``service`` but omit nested ``service.node`` for breadcrumbs. */
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
export function InventoryBreadcrumbs({ mockSchema }: { mockSchema?: PluginSchema }) {
  const location = useLocation();
  const { data: schema } = usePluginSchema('inventory', mockSchema);

  const prefix = useMemo(() => inventoryMountPrefix(location.pathname), [location.pathname]);

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

  const { data: record } = usePluginEntityDetail('inventory', entityName ?? '', id, undefined, {
    enabled: detailEnabled,
  });

  /** Service id for table breadcrumb enrichment: nested path segment or ``database.service_id``. */
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

  const { data: tableServiceEnrichment } = usePluginEntityDetail(
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

  const { data: schemaNodeEnrichment } = usePluginEntityDetail(
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

  const { data: serviceNodeEnrichment } = usePluginEntityDetail(
    'inventory',
    'nodes',
    serviceBreadcrumbNodeId,
    undefined,
    { enabled: fetchNodeForServiceCrumbs },
  );

  /** Merged entity detail for breadcrumbs (nested path + flat ``/tables/:id``). */
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
        schema?.entities?.find((e: PluginEntitySchema) => e.name === entityName)?.displayName ??
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
  }, [breadcrumbDisplayRecord, entityName, flat, id, nested, prefix, record, schema?.entities]);

  if (items.length === 0) {
    return null;
  }

  return (
    <Breadcrumbs sx={{ mb: 2 }} aria-label="Inventory breadcrumb">
      {items}
    </Breadcrumbs>
  );
}
