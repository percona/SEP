import { useCallback } from 'react';

export type DownloadLog = (filename: string, text: string) => void;

export function useLogDownload(): DownloadLog {
  return useCallback((filename: string, text: string) => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    // Defer revocation: Safari can race the anchor-triggered download if the
    // blob URL is revoked in the same tick as .click().
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }, []);
}
