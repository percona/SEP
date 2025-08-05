import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

const reactElement = document.getElementById('react');
if (reactElement) {
  const react = createRoot(reactElement);
  react.render(<App />);
} else {
  console.error("Element #react not found");
}
