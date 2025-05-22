const { useMemo, useState, useEffect } = React;

function SchemaList({ serviceId, onSelect }) {
  const [service, setService] = useState(null);
  const [schemas, setSchemas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [canSync, setCanSync] = useState(true);

  const fetchSchemas = async () => {
    try {
      const res = await axios.get(`/inventory/api/services/${serviceId}`);
      const { service, sync_is_running, can_sync } = res.data;
      setService(service);
      setSchemas(service.schemas || []);
      setLoading(sync_is_running);
      setCanSync(can_sync);
    } catch (err) {
      console.error("Error fetching service data:", err);
    }
  };

  useEffect(() => {
    fetchSchemas();
  }, [serviceId]);

  const handleSync = async () => {
    setLoading(true);
    try {
      await axios.post(`/inventory/api/services/${serviceId}/sync`);
      const interval = setInterval(async () => {
        try {
          const res = await axios.get(`/inventory/api/services/${serviceId}`);
          const { service, sync_is_running, can_sync } = res.data;
          setService(service);
          setSchemas(service.schemas || []);
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

  const handleDelete = async (schemaId) => {
    try {
      await axios.post(`/inventory/api/schemas/${schemaId}/delete`);
      fetchSchemas();
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const columns = useMemo(() => [
    { Header: 'Name', accessor: 'name' },
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
      {service && (
        <section>
          <h2 style={{ marginTop: 0 }}>Service Details</h2>
          <dl>
            <dt>Name</dt>
            <dd>{service.name}</dd>

            <dt>Type</dt>
            <dd>{service.type}</dd>

            {service.node?.source && (
              <>
                <dt>Source</dt>
                <dd>{service.node.source}</dd>
              </>
            )}

            {service.external_id && (
              <>
                <dt>External ID</dt>
                <dd>{service.external_id}</dd>
              </>
            )}

            <dt>Port</dt>
            <dd>{service.port}</dd>

            {service.environment && (
              <>
                <dt>Environment</dt>
                <dd>{service.environment}</dd>
              </>
            )}
          </dl>
          <hr style={{ borderColor: '#555' }} />
        </section>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Schemas on this Service</h2>
        <SyncButton loading={loading} canSync={canSync} onClick={handleSync} />
      </div>
      <DataTable data={schemas} columns={columns} onRowClick={onSelect} />
    </div>
  );
}
