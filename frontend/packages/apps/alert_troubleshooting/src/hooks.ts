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

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@sep/api';
import type { AlertDetailResponse, AlertGroup } from './types';

const API_BASE = '/apps/alert_troubleshooting';

export function useAlertGroups() {
  return useQuery<AlertGroup[]>({
    queryKey: ['alert_troubleshooting', 'groups'],
    queryFn: async () => {
      const { data } = await apiClient.get<AlertGroup[]>(`${API_BASE}/`);
      return data;
    },
  });
}

export function useAlertDetail(serviceType: string | undefined, alertName: string | undefined) {
  return useQuery<AlertDetailResponse>({
    queryKey: ['alert_troubleshooting', 'detail', serviceType, alertName],
    queryFn: async () => {
      const { data } = await apiClient.get<AlertDetailResponse>(
        `${API_BASE}/${encodeURIComponent(serviceType ?? '')}/${encodeURIComponent(alertName ?? '')}`,
      );
      return data;
    },
    enabled: Boolean(serviceType && alertName),
  });
}
