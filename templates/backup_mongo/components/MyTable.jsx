import React from "react";
import { Box, Stack } from "@mui/material";
import { Table } from "@percona/ui-lib";

// 2. Create some sample data.
const users = [
  { id: 1, name: "Alice", email: "alice@example.com", age: 28 },
  { id: 2, name: "Bob", email: "bob@example.com", age: 34 },
  { id: 3, name: "Charlie", email: "charlie@example.com", age: 45 },
];

// 3. Define the column configuration, specifying which keys to display
// and how to render them.
const userColumns = [
  {
    key: "id",
    header: "ID",
  },
  {
    key: "name",
    header: "Full Name",
  },
  {
    key: "email",
    header: "Email Address",
  },
  {
    key: "age",
    header: "Age",
  },
];

export default function MyTable() {
  return (
    <Stack alignItems="center">
      <Box>
        <Table data={users} columns={userColumns} />
      </Box>
    </Stack>
  );
}
