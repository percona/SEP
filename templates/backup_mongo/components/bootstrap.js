import React from 'react';
import { createRoot } from 'react-dom/client';
import MongoDBBackups from './MongoDBBackups';

const mongodbBackupElement = document.getElementById('mongodb_backups');
if (mongodbBackupElement) {
  const react = createRoot(mongodbBackupElement);
  react.render(<MongoDBBackups />);
} else {
  console.error("Element #mongodb_backups not found");
}
