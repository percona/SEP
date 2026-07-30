import { useState } from 'react';
import { Box, Paper, Tab, Tabs, Toolbar, Typography } from '@mui/material';
import { TopologyPanel } from './TopologyPanel';
import { UpgradePanel } from './UpgradePanel';
import type { HostTopology } from './types';

export function MongoUpgradePlugin() {
  const [activeTab, setActiveTab] = useState(0);
  const [topology, setTopology] = useState<HostTopology[]>([]);

  return (
    <Box sx={{ display: 'grid', gap: 2 }}>
      <Paper elevation={1} sx={{ p: 2 }}>
        <Toolbar sx={{ px: 0 }}>
          <Typography variant="h6" sx={{ flex: 1 }}>
            MongoDB Rolling Upgrade
          </Typography>
        </Toolbar>

        <Tabs value={activeTab} onChange={(_, v: number) => setActiveTab(v)} sx={{ mb: 2 }}>
          <Tab label="1 — Discover Topology" />
          <Tab label="2 — Plan Upgrade" disabled={topology.length === 0} />
        </Tabs>

        {activeTab === 0 && (
          <TopologyPanel
            topology={topology}
            onTopologyDiscovered={(t) => {
              setTopology(t);
              setActiveTab(1);
            }}
          />
        )}

        {activeTab === 1 && (
          <UpgradePanel topology={topology} onBack={() => setActiveTab(0)} />
        )}
      </Paper>
    </Box>
  );
}
