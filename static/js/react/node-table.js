const {
    useState,
    useEffect
} = React;

function NodeTable() {
    const [data, setData] = React.useState(null);

    React.useEffect(() => {
        axios.get("/inventory/api/nodes")
            .then(res => setData(res.data))
            .catch(err => console.error(err));
    }, []);

    return ( <
        div >
        <
        h2 > Node List < /h2> <
        table data - table >
        <
        thead >
        <
        tr >
        <
        th > Name < /th> <
        th > Address < /th> <
        th > Type < /th> <
        th > Source < /th> <
        th > Actions < /th> < /
        tr > <
        /thead> <
        tbody >
        <
        tr >
        <
        td > Test < /td> <
        td > 127.0 .0 .1 < /td> <
        td > MySQL < /td> <
        td > T < /td> <
        td >
        <
        input type = "hidden"
        name = "csrf-token"
        value = "{{ csrf_token }}" / >
        <
        button name = "location"
        class = "icons submitButton" >
        <
        span class = "material-symbols-outlined" > delete_forever < /span> < /
        button > <
        /td> < /
        tr > <
        /tbody> < /
        table > <
        /div>
    );
}
