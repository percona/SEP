// vite_remote/src/App.jsx
import React, { useState } from 'react';

const App = () => {
  const [count, setCount] = useState(0);

  return (
    <div style={{ padding: '20px', border: '2px solid #007bff', borderRadius: '8px', textAlign: 'center' }}>
      <h1>Set Remote App</h1>
      <p>This is a component loaded via Module Federation.</p>
      <p>Count: {count}</p>
      <button onClick={() => setCount(c => c + 1)}>
        Increment
      </button>
    </div>
  );
};

export default App;

