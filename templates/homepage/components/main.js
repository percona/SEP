import React from 'react';
import { createRoot } from 'react-dom/client';
import Tasks from './Tasks';

const runningTasks = document.getElementById('tasks_table');
if (runningTasks) {
  const react = createRoot(runningTasks);
  react.render(<Tasks />);

} else {
  console.error("Element #tasks_table not found");
}