/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { memo } from 'react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type { MySQLNodeData } from './types';

type MySQLFlowNode = Node<MySQLNodeData & Record<string, unknown>, 'mysql'>;

function readOnlyColor(mode?: string | null): 'default' | 'success' | 'warning' | 'error' {
  if (mode === 'RW') {
    return 'success';
  }
  if (mode === 'RO') {
    return 'warning';
  }
  if (mode === 'SR') {
    return 'error';
  }
  return 'default';
}

function MySQLNodeBase({ data }: NodeProps<MySQLFlowNode>) {
  const d = data as MySQLNodeData;
  const isError = d.status === 'error';
  const server = d.server ?? {};
  const repl = d.replication ?? {};
  return (
    <Box
      sx={{
        bgcolor: 'background.paper',
        border: 1,
        borderColor: isError ? 'error.main' : 'divider',
        borderRadius: 2,
        boxShadow: 1,
        px: 1.5,
        py: 1,
        width: 240,
        minHeight: 110,
      }}
      data-testid={`mysql-node-${d.host_entry}`}
    >
      <Handle type="target" position={Position.Left} />
      <Stack spacing={0.5}>
        <Typography variant="subtitle2" noWrap title={d.host_entry}>
          {d.host_entry}
        </Typography>
        {isError ? (
          <Typography variant="caption" color="error" noWrap title={d.error ?? ''}>
            {d.error ?? 'collection failed'}
          </Typography>
        ) : (
          <>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Chip
                size="small"
                color={readOnlyColor(server.read_only)}
                label={server.read_only ?? '—'}
              />
              {server.version ? (
                <Typography variant="caption" color="text.secondary" noWrap>
                  v{server.version.split('-')[0]}
                </Typography>
              ) : null}
              {d.gtid_mode ? (
                <Chip size="small" variant="outlined" label={`GTID:${d.gtid_mode}`} />
              ) : null}
            </Stack>
            {repl.source_host ? (
              <Stack direction="row" spacing={0.5} alignItems="center">
                <Chip
                  size="small"
                  color={repl.repl_status === 'ok' ? 'success' : 'error'}
                  label={`repl:${repl.repl_status ?? '?'}`}
                />
                {typeof repl.seconds_behind === 'number' ? (
                  <Typography variant="caption" color="text.secondary">
                    {repl.seconds_behind}s behind
                  </Typography>
                ) : null}
              </Stack>
            ) : null}
            {d.cluster ? (
              <Typography variant="caption" color="primary" noWrap>
                cluster: {d.cluster.cluster_name} ({d.cluster.cluster_size ?? '?'})
              </Typography>
            ) : null}
          </>
        )}
      </Stack>
      <Handle type="source" position={Position.Right} />
    </Box>
  );
}

export const MySQLNode = memo(MySQLNodeBase);
