const { useMemo, useState } = React;

function ServiceList({ nodeId, onSelect }) {
  const [node, setNode] = useState(null);
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);

  const fetchServices = async () => {
    try {
      const res = await axios.get(`/inventory/api/nodes/${nodeId}`);
      const { node, sync_is_running, can_sync } = res.data;
      setNode(node);
      setServices(node.services || []);
      setLoading(sync_is_running);
      setCanSync(can_sync);
    } catch (err) {
      console.error(err);
    }
  };

  React.useEffect(() => {
    fetchServices();
  }, [nodeId]);

  const handleSync = async () => {
    setLoading(true);
    try {
      await axios.post(`/inventory/api/nodes/${nodeId}/sync`);
      const interval = setInterval(async () => {
        const res = await axios.get(`/inventory/api/nodes/${nodeId}`);
        const { node, sync_is_running, can_sync } = res.data;
        setNode(node);
        setServices(node.services || []);
        setLoading(sync_is_running);
        setCanSync(can_sync);
        if (!sync_is_running) clearInterval(interval);
      }, 3000);
    } catch (err) {
      console.error("Sync failed:", err);
      setLoading(false);
    }
  };

  const columns = useMemo(() => [
    { Header: 'Name', accessor: 'name' },
    { Header: 'Type', accessor: 'type' },
    { Header: 'Port', accessor: 'port' },
    { Header: 'External ID', accessor: 'external_id' },
  ], []);

  return (
    <div>
      {node && (
        <div>
          <h2 style={{ marginTop: 0 }}>Node Details</h2>
          <dl>
            <dt>Name</dt>
            <dd>{node.name}</dd>
            <dt>Address</dt>
            <dd>{node.address}</dd>
            <dt>Type</dt>
            <dd>{node.type}</dd>
            {node.source && (
              <>
                <dt>Source</dt>
                <dd>{node.source}</dd>

                {node.external_id && (
                  <>
                    <dt>External ID</dt>
                    <dd>{node.external_id}</dd>
                  </>
                )}
              </>
            )}
          </dl>
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Services on this Node</h2>
        <SyncButton loading={loading} canSync={canSync} onClick={handleSync} />
      </div>
      <DataTable data={services} columns={columns} onRowClick={onSelect} />
    </div>
  );
}