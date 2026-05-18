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
import type { ClusterNodeData } from './types';

type ClusterFlowNode = Node<ClusterNodeData & Record<string, unknown>, 'cluster'>;

function ClusterGroupBase({ data }: NodeProps<ClusterFlowNode>) {
  const d = data as ClusterNodeData;
  return (
    <Box
      sx={{
        border: 2,
        borderStyle: 'dashed',
        borderColor: 'primary.main',
        borderRadius: 2,
        bgcolor: 'action.hover',
        px: 2,
        py: 1.5,
        minWidth: 200,
        minHeight: 90,
      }}
      data-testid={`cluster-node-${d.cluster_name}`}
    >
      <Handle type="target" position={Position.Left} />
      <Stack spacing={0.5}>
        <Typography variant="overline" color="primary" sx={{ lineHeight: 1.1 }}>
          PXC Cluster
        </Typography>
        <Typography variant="subtitle2" noWrap>
          {d.cluster_name}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {d.size ?? '?'} nodes · {d.status ?? 'unknown'}
        </Typography>
        <Typography variant="caption" color="text.disabled">
          {d.members.length} member{d.members.length === 1 ? '' : 's'}
        </Typography>
      </Stack>
      <Handle type="source" position={Position.Right} />
    </Box>
  );
}

export const ClusterGroup = memo(ClusterGroupBase);
