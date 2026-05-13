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
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type { UnknownSourceNodeData } from './types';

type UnknownFlowNode = Node<UnknownSourceNodeData & Record<string, unknown>, 'unknown_source'>;

function UnknownSourceNodeBase({ data }: NodeProps<UnknownFlowNode>) {
  const d = data as UnknownSourceNodeData;
  return (
    <Box
      sx={{
        border: 1,
        borderStyle: 'dotted',
        borderColor: 'warning.main',
        borderRadius: 2,
        bgcolor: 'warning.light',
        opacity: 0.85,
        px: 1.5,
        py: 1,
        minWidth: 200,
        minHeight: 80,
      }}
      data-testid={`unknown-node-${d.address ?? 'unknown'}-${d.port ?? 0}`}
    >
      <Handle type="target" position={Position.Left} />
      <Stack spacing={0.5}>
        <Typography variant="overline" color="warning.dark" sx={{ lineHeight: 1.1 }}>
          Unknown source
        </Typography>
        <Typography variant="subtitle2" noWrap>
          {d.address ?? 'unknown'}:{d.port ?? 0}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {d.reason ?? 'Not in inventory'}
        </Typography>
      </Stack>
      <Handle type="source" position={Position.Right} />
    </Box>
  );
}

export const UnknownSourceNode = memo(UnknownSourceNodeBase);
