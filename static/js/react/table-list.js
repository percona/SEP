const { useMemo, useState } = React;

function TableList({ schemaId }) {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);

  const fetchTables = async () => {
    try {
      const res = await axios.get(`/inventory/api/schemas/${schemaId}`);
      setTables(res.data.schema.tables);
      setCanSync(true);
    } catch (err) {
      console.error(err);
    }
  };

  React.useEffect(() => {
    fetchTables();
  }, [schemaId]);

  const handleSync = async () => {
    setLoading(true);
    try {
      await axios.post(`/inventory/api/schemas/${schemaId}/sync/`);
      const interval = setInterval(async () => {
        const res = await axios.get(`/inventory/api/schemas/${schemaId}`);
        setTables(res.data.schema.tables);
        const isRunning = res.data.schema.tables.some(t => t.is_running);
        if (!isRunning) {
          clearInterval(interval);
          setLoading(false);
        }
      }, 3000);
    } catch (err) {
      console.error("Sync failed:", err);
      setLoading(false);
    }
  };

  const columns = useMemo(() => [
    { Header: 'Name', accessor: 'name' },
    { Header: 'Create Statement', accessor: 'create' },
  ], []);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Tables on this Schema</h2>
        {canSync && (
          <button
            onClick={handleSync}
            disabled={loading}
            className="icons"
            style={{ display: 'inline' }}
          >
            <span
              className="material-symbols-outlined"
              style={{
                animation: loading ? 'spin 1s linear infinite' : 'none',
                display: 'inline-block'
              }}
            >
              autorenew
            </span>
          </button>
        )}
      </div>
      <DataTable data={tables} columns={columns} />
    </div>
  );
}
