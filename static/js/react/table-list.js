const { useMemo, useState, useEffect } = React;

function TableList({ schemaId }) {
  const [schema, setSchema] = useState(null);
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);
  const [expandedRows, setExpandedRows] = useState({}); // Track expanded rows by table ID

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

  const toggleRow = (id) => {
    setExpandedRows((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const columns = useMemo(() => [
    {
      Header: 'Name',
      accessor: 'name',
      Cell: ({ row }) => (
        <span
          style={{ cursor: 'pointer', color: '#007bff' }}
          onClick={() => toggleRow(row.original.id)}
        >
          {row.original.name}
        </span>
      )
    },
    {
      Header: 'Create Statement',
      accessor: 'create',
      width: 500,
      Cell: ({ row }) => {
        const isExpanded = expandedRows[row.original.id];
        const value = row.original.create;
        return (
          <pre style={{ whiteSpace: 'pre-wrap', maxWidth: 500, overflowX: 'auto' }}>
            <code className="language-sql">
              {isExpanded ? value : value.slice(0, 200) + (value.length > 200 ? ' ...' : '')}
            </code>
          </pre>
        );
      }
    },
    {
      Header: 'Keys',
      accessor: 'keys',
      width: 400,
      Cell: ({ row }) => {
        const isExpanded = expandedRows[row.original.id];
        const value = row.original.keys;
        const json = JSON.stringify(value, null, isExpanded ? 2 : 0);
        return (
          <pre style={{ whiteSpace: 'pre-wrap', maxWidth: 400, overflowX: 'auto' }}>
            <code className="language-json">{json}{!isExpanded && json.length > 200 ? ' ...' : ''}</code>
          </pre>
        );
      }
    },
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
  ], [expandedRows]);

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
