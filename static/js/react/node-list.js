const { useMemo, useState } = React;

function NodeList({ onSelect }) {
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);

  const fetchNodes = () => {

    axios.get("/inventory/api/nodes")
      .then(res => {
        setNodes(res.data.inventory);
        setLoading(res.data.sync_is_running);
        setCanSync(res.data.can_sync);
      })
      .catch(err => console.error(err));
  }

  React.useEffect(() => {
    fetchNodes();
  }, []);

  const handleSync = async () => {
    setLoading(true);
    try {
      await axios.post("/inventory/api/nodes/sync");
      const interval = setInterval(async () => {
        const res = await axios.get("/inventory/api/nodes");
        setNodes(res.data.inventory);
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
  }

  const columns = [
    { Header: 'Name', accessor: 'name' },
    { Header: 'Address', accessor: 'address' },
    { Header: 'Type', accessor: 'type' },
    { Header: 'Source', accessor: 'source' },
    { Header: 'External ID', accessor: 'external_id' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Node List</h2>
        <SyncButton loading={loading} canSync={canSync} onClick={handleSync} />
      </div>
      <DataTable data={nodes} columns={columns} onRowClick={onSelect} />
    </div>
  );
}