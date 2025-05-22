const { useState } = React;

function Separator() {
  return (
    <span style={{ margin: '0 8px', color: '#888' }}>{'>'}</span>
  );
}

function Inventory() {
  const [level, setLevel] = useState('nodes');
  const [selected, setSelected] = useState({
    node: null,
    service: null,
    schema: null,
  });

  const goToServices = (node) => {
    setSelected({ node, service: null, schema: null });
    setLevel('services');
  };

  const goToSchemas = (service) => {
    setSelected(prev => ({ ...prev, service, schema: null }));
    setLevel('schemas');
  };

  const goToTables = (schema) => {
    setSelected(prev => ({ ...prev, schema }));
    setLevel('tables');
  };
  const handleBreadcrumbClick = (targetLevel) => {
    switch (targetLevel) {
      case 'nodes':
        setLevel('nodes');
        setSelected({ node: null, service: null, schema: null });
        break;
      case 'services':
        setLevel('services');
        setSelected(prev => ({ ...prev, service: null, schema: null }));
        break;
      case 'schemas':
        setLevel('schemas');
        setSelected(prev => ({ ...prev, schema: null }));
        break;
    }
  };

  const renderBreadcrumbs = () => {
    return (
      <div style={{ marginBottom: '16px' }}>
        <span style={{ cursor: 'pointer' }}><a href="/">Home</a></span>
        <Separator/>
        <span style={{ cursor: 'pointer' }} onClick={() => handleBreadcrumbClick('nodes')}>
          Inventory
        </span>
        {selected.node && (
          <>
            <Separator/>
            <span style={{ cursor: 'pointer' }} onClick={() => handleBreadcrumbClick('services')}>
              {selected.node.name}
            </span>
          </>
        )}
        {selected.service && (
          <>
            <Separator/>
            <span style={{ cursor: 'pointer' }} onClick={() => handleBreadcrumbClick('schemas')}>
              {selected.service.name}
            </span>
          </>
        )}
        {selected.schema && (
          <>
            <Separator/>
            <span>{selected.schema.name}</span>
          </>
        )}
      </div>
    );
  };

  const renderCurrentView = () => {
    switch (level) {
      case 'nodes':
        return <NodeList onSelect={goToServices} />;
      case 'services':
        return <ServiceList nodeId={selected.node.id} onSelect={goToSchemas} />;
      case 'schemas':
        return <SchemaList serviceId={selected.service.id} onSelect={goToTables} />;
      case 'tables':
        return <TableList schemaId={selected.schema.id} />;
      default:
        return <div>Unknown level</div>;
    }
  };

  return (
    <div>
      {renderBreadcrumbs()}
      {renderCurrentView()}
    </div>
  );
}
