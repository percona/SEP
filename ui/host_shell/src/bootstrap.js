import React from 'react';
import { createRoot } from 'react-dom/client';
import Inventory from './Inventory';
import MongoDBBackups from './MongoDBBackups';

const inventoryElement = document.getElementById('inventory');
if (inventoryElement) {
  const react = createRoot(inventoryElement);
  react.render(<Inventory />);
} else {
  console.error("Element #inventory not found");
}


const mongodbBackupElement = document.getElementById('mongodb_backups');
if (mongodbBackupElement) {
  const react = createRoot(mongodbBackupElement);
  react.render(<MongoDBBackups />);
} else {
  console.error("Element #mongodb_backups not found");
}
