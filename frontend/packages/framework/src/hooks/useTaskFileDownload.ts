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

import { useMutation } from '@tanstack/react-query';
import { apiClient } from '@sep/api';

export interface TaskFileDownloadParams {
  taskHistoryId: number;
  /** Relative path of the file/directory as returned by the files list. */
  path: string;
  isDir: boolean;
}

export function useTaskFileDownload() {
  return useMutation<void, Error, TaskFileDownloadParams>({
    mutationFn: async ({ taskHistoryId, path, isDir }) => {
      const { data } = await apiClient.get<Blob>(`/files/${taskHistoryId}/download`, {
        baseURL: '',
        params: { path },
        responseType: 'blob',
      });
      const name = path.split('/').filter(Boolean).pop() ?? path;
      const suggestedName = isDir ? `${name}.tar.gz` : name;
      const url = URL.createObjectURL(data);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = suggestedName;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        // Defer revocation: Safari and Firefox can race the anchor-triggered
        // download if the blob URL is revoked in the same tick as .click().
        setTimeout(() => URL.revokeObjectURL(url), 0);
      }
    },
  });
}
