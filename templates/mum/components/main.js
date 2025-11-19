import React from 'react';
import { createRoot } from 'react-dom/client';
import Mum from './Mum';

const mum = document.getElementById('mum');
if (mum) {
  const react = createRoot(mum);
  react.render(<Mum />);

} else {
  console.error("Element #mum not found");
}