const { useMemo, useState } = React;

function ServiceList({ nodeId, onSelect }) {
  const [services, setServices] = useState([])

  React.useEffect(() => {
    axios.get(`/inventory/api/nodes/${nodeId}`)
      .then(res => {
        setServices(res.data.node.services)
      })
      .catch(err => console.error(err));
  }, []);

  const columns = [
    { Header: 'Name', accessor: 'name' },
    { Header: 'Type', accessor: 'type' },
    { Header: 'Port', accessor: 'port' },
    { Header: 'External ID', accessor: 'external_id' },
  ];

  return (
    <div>
      <h1>Services on this Node</h1>
      <DataTable data={services} columns={columns} onRowClick={onSelect}/>
    </div>
  )
}

