const { useMemo, useState } = React;

function SchemaList({ serviceId, onSelect }) {
  const [schemas, setSchemas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);

  const fetchSchemas = async () => {
    try {
      const res = await axios.get(`/inventory/api/services/${serviceId}`);
      setSchemas(res.data.service.schemas);
      setCanSync(true);
    } catch (err) {
      console.error(err);
    }
  };

  React.useEffect(() => {
    fetchSchemas();
  }, [serviceId]);

  const handleSync = async () => {
    setLoading(true);
    try {
      await axios.post(`/inventory/api/services/${serviceId}/sync`);
      const interval = setInterval(async () => {
        const res = await axios.get(`/inventory/api/services/${serviceId}`);
        setSchemas(res.data.service.schemas);
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
  ], []);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Schemas on this Service</h2>
        <SyncButton loading={loading} canSync={canSync} onClick={handleSync} />
      </div>
      <DataTable data={schemas} columns={columns} onRowClick={onSelect} />
    </div>
  );
}
