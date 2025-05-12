const { useMemo, useState } = React;

function ServiceList({ nodeId, onSelect }) {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);

  const fetchServices = async () => {
    try {
      const res = await axios.get(`/inventory/api/nodes/${nodeId}`);
      setServices(res.data.node.services);
      setCanSync(true);
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
        setServices(res.data.node.services);
        setLoading(res.data.sync_is_running);
        setCanSync(res.data.can_sync);
        if (!res.data.sync_is_running) {
          clearInterval(interval);
        }
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Services on this Node</h2>
        <SyncButton loading={loading} canSync={canSync} onClick={handleSync} />
      </div>
      <DataTable data={services} columns={columns} onRowClick={onSelect} />
    </div>
  );
}