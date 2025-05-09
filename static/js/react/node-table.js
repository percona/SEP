const { useMemo, useState } = React;
const {
  useTable,
  useSortBy,
  usePagination,
  useGlobalFilter
} = ReactTable;


function NodeTable() {
  const [nodes, setNodes] = useState([])

  React.useEffect(() => {
    axios.get("/inventory/api/nodes")
      .then(res => {
        console.log(res.data.inventory)
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
      <DataTable data={nodes} columns={columns} onRowClick={(row) => console.log("Clicked row:", row)}/>
    </div>
  )
}

