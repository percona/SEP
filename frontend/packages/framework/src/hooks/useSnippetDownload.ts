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
import { apiClient, normalizeBlobError } from '@sep/api';
import { downloadBlob } from '../utils/downloadBlob';

export interface SnippetDownloadParams {
  /** Snippet filename, relative to the snippets root, as returned by the list. */
  filename: string;
}

export function useSnippetDownload() {
  return useMutation<void, Error, SnippetDownloadParams>({
    mutationFn: async ({ filename }) => {
      let data: Blob;
      try {
        ({ data } = await apiClient.get<Blob>('/apps/snippets/snippet/download', {
          params: { snippet_filename: filename },
          responseType: 'blob',
        }));
      } catch (error) {
        // The response type applies to the error body too, so a refusal's JSON
        // reason arrives as a blob. Parse it, or the caller can only report the
        // bare status code.
        throw await normalizeBlobError(error);
      }
      const name = filename.split('/').filter(Boolean).pop() ?? filename;
      downloadBlob(data, name);
    },
  });
}
