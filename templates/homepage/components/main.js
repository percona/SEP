import React from 'react';
import { createRoot } from 'react-dom/client';
import RunningTasks from './RunningTasks';

const runningTasks = document.getElementById('react_running');
if (runningTasks) {
  const react = createRoot(runningTasks);
  react.render(<RunningTasks />);

} else {
  console.error("Element #react_running not found");
}