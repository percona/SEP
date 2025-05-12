const { useMemo, useState, useEffect } = React;

function TableList({ schemaId }) {
  const [schema, setSchema] = useState(null);
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);

  const fetchTables = async () => {
    try {
      const res = await axios.get(`/inventory/api/schemas/${schemaId}`);
      const { schema, sync_is_running, can_sync } = res.data;
      setSchema(schema);
      setTables(schema.tables || []);
      setLoading(sync_is_running);
      setCanSync(can_sync);
    } catch (err) {
      console.error("Error fetching schema data:", err);
    }
  };

  useEffect(() => {
    fetchTables();
  }, [schemaId]);

  const handleSync = async () => {
    setLoading(true);
    try {
      await axios.post(`/inventory/api/schemas/${schemaId}/sync/`);
      const interval = setInterval(async () => {
        try {
          const res = await axios.get(`/inventory/api/schemas/${schemaId}`);
          const { schema, sync_is_running, can_sync } = res.data;
          setSchema(schema);
          setTables(schema.tables || []);
          setLoading(sync_is_running);
          setCanSync(can_sync);
          if (!sync_is_running) clearInterval(interval);
        } catch (err) {
          console.error("Polling failed:", err);
          clearInterval(interval);
        }
      }, 3000);
    } catch (err) {
      console.error("Sync failed:", err);
      setLoading(false);
    }
  };

  const handleDelete = async (tableId) => {
    try {
      await axios.post(`/inventory/api/tables/${tableId}/delete`);
      fetchTables();
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const columns = useMemo(() => [
    { Header: 'Name', accessor: 'name' },
    { Header: 'Create Statement', accessor: 'create' },
    {
      Header: 'Actions',
      accessor: 'id',
      Cell: ({ value }) => (
        <div style={{ display: 'inline' }} className="confirmable-form">
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleDelete(value);
            }}
            name="location"
            className="icons submitButton"
            style={{ background: 'none', border: 'none', cursor: 'pointer' }}
          >
            <span className="material-symbols-outlined">delete_forever</span>
          </button>
        </div>
      ),
    }
  ], []);

  return (
    <div>
      {schema && (
        <section> 
          <h2 style={{ marginTop: 0 }}>Schema Details</h2>
          <dl>
            <dt>Name</dt>
            <dd>{schema.name}</dd>
          </dl>
          <hr style={{ borderColor: '#555' }} />
        </section>
      )}

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
                display: 'inline-block',
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
