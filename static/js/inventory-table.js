const { useState, useEffect } = React;

function AxiosExample() {
    const [data, setData] = React.useState(null);

    React.useEffect(() => {
      axios.get("/inventory/api/nodes")
        .then(res => setData(res.data))
        .catch(err => console.error(err));
    }, []);

    return (
      <div>
        <h2>Inventory</h2>
        {data ? <pre>{JSON.stringify(data.inventory, null, 2)}</pre> : <p>Loading...</p>}
      </div>
    );
}