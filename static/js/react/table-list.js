const { useMemo, useState } = React;

function TableList({ schemaId}) {
  const [tables, setTables] = useState([])

  React.useEffect(() => {
    axios.get(`/inventory/api/schemas/${schemaId}`)
      .then(res => {
        setTables(res.data.schema.tables)
      })
      .catch(err => console.error(err));
  }, []);

  const columns = [
    { Header: 'Name', accessor: 'name' },
    { Header: 'Create Statement', accessor: 'create' },
  ];

  return (
    <div>
      <h1>Tables on this Schema</h1>
      <DataTable data={tables} columns={columns}/>
    </div>
  )
}

