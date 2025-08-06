import { Box, Stack } from '@mui/material';
import { Table } from '@percona/ui-lib';
export default function MyTable() {
    return (
         <Stack alignItems="center">
           <Box >
             <Table tableName={''} columns={[]} data={[]}></Table>
           </Box>
         </Stack>
       )
}
