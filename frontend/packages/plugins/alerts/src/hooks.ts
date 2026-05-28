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

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@sep/api';
import type { AlertBackupDetail, AlertIndexResponse, PushResponse } from './types';

const API_BASE = '/plugins/alerts';

export function useAlertsIndex() {
  return useQuery<AlertIndexResponse>({
    queryKey: ['alerts', 'index'],
    queryFn: async () => {
      const { data } = await apiClient.get<AlertIndexResponse>(`${API_BASE}/`);
      return data;
    },
  });
}

export function useAlertBackupDetail(backupId: number | undefined) {
  return useQuery<AlertBackupDetail>({
    queryKey: ['alerts', 'backup', backupId],
    queryFn: async () => {
      const { data } = await apiClient.get<AlertBackupDetail>(`${API_BASE}/backups/${backupId}`);
      return data;
    },
    enabled: backupId !== undefined,
  });
}

export function usePushTemplates() {
  const queryClient = useQueryClient();
  return useMutation<PushResponse, Error, { selectedTemplates: string[] }>({
    mutationFn: async ({ selectedTemplates }) => {
      const { data } = await apiClient.post<PushResponse>(`${API_BASE}/push`, {
        selected_templates: selectedTemplates,
      });
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}

export function useRestoreBackup() {
  const queryClient = useQueryClient();
  return useMutation<{ status: string }, Error, { backupId: number }>({
    mutationFn: async ({ backupId }) => {
      const { data } = await apiClient.post<{ status: string }>(`${API_BASE}/restore`, {
        backup_id: backupId,
      });
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}

export function useSavePagerDuty() {
  const queryClient = useQueryClient();
  return useMutation<{ status: string }, Error, { integrationKey: string }>({
    mutationFn: async ({ integrationKey }) => {
      const { data } = await apiClient.post<{ status: string }>(`${API_BASE}/pagerduty`, {
        integration_key: integrationKey,
      });
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}

export function useDeletePagerDuty() {
  const queryClient = useQueryClient();
  return useMutation<{ status: string }, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<{ status: string }>(`${API_BASE}/pagerduty/delete`, {});
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}
