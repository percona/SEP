import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, CircularProgress, Typography } from '@mui/material';
import { useFormContext, useWatch } from 'react-hook-form';
import type { ScriptPreviewField as ScriptPreviewFieldType } from '../types';

interface ScriptPreviewFieldProps {
  field: ScriptPreviewFieldType;
}

interface ScriptPreviewResponse {
  content: string;
  language: string;
  is_truncated: boolean;
}

interface PreviewState {
  status: 'idle' | 'loading' | 'success' | 'error';
  data: ScriptPreviewResponse | null;
  error: string | null;
}

const DEBOUNCE_MS = 300;

/**
 * Read-only field that renders a backend-fetched script preview.
 *
 * Fetches `endpointUrl` on mount and re-fetches whenever any sibling field
 * listed in `dependsOn` changes value — debounced and cancellation-safe via
 * an AbortController. Renders the response's `content` inside a `<pre>`
 * block annotated with the chosen highlighter language; visual syntax
 * highlighting is intentionally deferred to a later ticket so this
 * migration does not pull in a new bundle dependency.
 */
export function ScriptPreviewField({ field }: ScriptPreviewFieldProps) {
  const { control } = useFormContext();
  const dependsOnValues = useWatch({
    control,
    name: field.dependsOn,
  });
  const dependsOnKey = useMemo(() => JSON.stringify(dependsOnValues ?? []), [dependsOnValues]);

  const [state, setState] = useState<PreviewState>({
    status: 'idle',
    data: null,
    error: null,
  });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const handle = setTimeout(
      () => {
        setState((prev) => ({ ...prev, status: 'loading', error: null }));
        fetch(field.endpointUrl, { signal: controller.signal })
          .then(async (response) => {
            if (!response.ok) {
              throw new Error(`Preview unavailable (HTTP ${response.status})`);
            }
            const data = (await response.json()) as ScriptPreviewResponse;
            setState({ status: 'success', data, error: null });
          })
          .catch((error: unknown) => {
            if (controller.signal.aborted) {
              return;
            }
            const message = error instanceof Error ? error.message : 'Preview unavailable';
            setState({ status: 'error', data: null, error: message });
          });
      },
      field.dependsOn.length > 0 ? DEBOUNCE_MS : 0,
    );

    return () => {
      clearTimeout(handle);
      controller.abort();
    };
  }, [field.endpointUrl, field.dependsOn.length, dependsOnKey]);

  return (
    <Box
      sx={{
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        p: 1,
        backgroundColor: (theme) =>
          theme.palette.mode === 'light' ? theme.palette.grey[50] : theme.palette.grey[900],
      }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        {field.label}
      </Typography>
      {state.status === 'loading' && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
          <CircularProgress size={20} aria-label="Loading preview" />
        </Box>
      )}
      {state.status === 'error' && (
        <Alert severity="error" variant="outlined">
          {state.error ?? 'Preview unavailable'}
        </Alert>
      )}
      {state.status === 'success' && state.data && (
        <>
          {state.data.is_truncated && (
            <Typography variant="caption" color="text.secondary">
              Preview truncated.
            </Typography>
          )}
          <Box
            component="pre"
            data-language={state.data.language || field.language || 'plaintext'}
            sx={{
              m: 0,
              overflow: 'auto',
              fontFamily: 'monospace',
              fontSize: '0.85rem',
              maxHeight: '400px',
              whiteSpace: 'pre',
            }}
          >
            <code>{state.data.content}</code>
          </Box>
        </>
      )}
    </Box>
  );
}
