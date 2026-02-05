import React from 'react';
import { createRoot } from 'react-dom/client';
import Tasks from './Tasks';

const runningTasks = document.getElementById('react_running');
if (runningTasks) {
  const react = createRoot(runningTasks);
  react.render(<Tasks />);

} else {
  console.error("Element #react_running not found");
}