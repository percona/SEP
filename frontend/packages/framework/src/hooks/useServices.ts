import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiClient, type InventoryComponents } from '@sep/api';

export type ServiceType = InventoryComponents['schemas']['ServiceTypeEnum'];

export interface ServiceOption {
  id: number;
  name: string;
  type: ServiceType;
}

type PaginatedServices = InventoryComponents['schemas']['PaginatedResponse_ServiceResponse_'];

export interface UseServicesOptions {
  serviceTypes?: readonly ServiceType[];
  enabled?: boolean;
}

const DEFAULT_LIMIT = 200;

const STABLE_EMPTY: readonly ServiceType[] = Object.freeze([] as ServiceType[]);

function normaliseTypes(types: readonly ServiceType[] | undefined): readonly ServiceType[] {
  if (!types || types.length === 0) {
    return STABLE_EMPTY;
  }
  return [...types].sort();
}

async function fetchServicesPage(
  serviceType: ServiceType | undefined,
  offset: number,
): Promise<PaginatedServices> {
  const params: Record<string, string | number> = { offset, limit: DEFAULT_LIMIT };
  if (serviceType) {
    params.service_type = serviceType;
  }
  const { data } = await apiClient.get<PaginatedServices>('/api/inventory/services/', { params });
  return data;
}

async function fetchServicesForType(
  serviceType: ServiceType | undefined,
): Promise<ServiceOption[]> {
  const out: ServiceOption[] = [];
  let offset = 0;
  for (;;) {
    const page = await fetchServicesPage(serviceType, offset);
    for (const svc of page.items) {
      if (svc.id !== null && svc.id !== undefined) {
        out.push({ id: svc.id, name: svc.name, type: svc.type });
      }
    }
    offset += page.items.length;
    if (offset >= page.total || page.items.length === 0) {
      break;
    }
  }
  return out;
}

/**
 * Fetch services from the inventory API, optionally filtered to one or more
 * service types. Multiple types fan out to parallel paginated requests because
 * the upstream `/services/` endpoint accepts a single `service_type` only.
 */
export function useServices(
  options: UseServicesOptions = {},
): UseQueryResult<ServiceOption[], Error> {
  const { enabled = true } = options;
  const types = normaliseTypes(options.serviceTypes);
  return useQuery<ServiceOption[], Error>({
    queryKey: ['inventory', 'services', { types }],
    enabled,
    staleTime: 60_000,
    queryFn: async () => {
      if (types.length === 0) {
        return fetchServicesForType(undefined);
      }
      const pages = await Promise.all(types.map((t) => fetchServicesForType(t)));
      const seen = new Set<number>();
      const out: ServiceOption[] = [];
      for (const page of pages) {
        for (const svc of page) {
          if (!seen.has(svc.id)) {
            seen.add(svc.id);
            out.push(svc);
          }
        }
      }
      return out;
    },
  });
}
