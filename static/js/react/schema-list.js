const { useMemo, useState } = React;

function SchemaList({ serviceId, onSelect }) {
  const [schemas, setSchemas] = useState([])

  React.useEffect(() => {
    axios.get(`/inventory/api/services/${serviceId}`)
      .then(res => {
        setSchemas(res.data.service.schemas)
      })
      .catch(err => console.error(err));
  }, []);

  const columns = [
    { Header: 'Name', accessor: 'name' },
  ];

  return (
    <div>
      <h1>Schemas on this Service</h1>
      <DataTable data={schemas} columns={columns} onRowClick={onSelect}/>
    </div>
  )
}

