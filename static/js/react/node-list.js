const { useMemo, useState } = React;

function NodeList({ onSelect }) {
  const [nodes, setNodes] = useState([])

  React.useEffect(() => {
    axios.get("/inventory/api/nodes")
      .then(res => {
        setNodes(res.data.inventory)
      })
      .catch(err => console.error(err));
  }, []);

  const columns = [
    { Header: 'Name', accessor: 'name' },
    { Header: 'Address', accessor: 'address' },
    { Header: 'Type', accessor: 'type' },
    { Header: 'Source', accessor: 'source' },
    { Header: 'External ID', accessor: 'external_id' },
  ];

  return (
    <div>
      <h1>Node List</h1>
      <DataTable data={nodes} columns={columns} onRowClick={onSelect}/>
    </div>
  )
}

