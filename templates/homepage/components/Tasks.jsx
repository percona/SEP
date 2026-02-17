import React, { useEffect, useMemo, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import {
  Box,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Tooltip,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import { format } from "date-fns";
import axios from "axios";

const queryClient = new QueryClient();

const fetchTasksHistory = async () => {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const { data } = await axios.get("/tasks/ui/history");
  return data;
};

const formatDateTime = (value) => {
  if (!value) {
    return "";
  }
  return format(new Date(value), "yyyy-MM-dd HH:mm:ss");
};

const ROWS_PER_PAGE = 10;

const statusChipColor = (status) => {
  if (!status) {
    return "default";
  }

  switch (status.toLowerCase()) {
    case "success":
      return "success";
    case "failed":
      return "error";
    case "running":
      return "info";
    case "pending":
      return "warning";
    default:
      return "default";
  }
};

const TasksTable = () => {
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["tasks_history"],
    queryFn: fetchTasksHistory,
  });
  const [page, setPage] = useState(0);

  if (error) {
    return (
      <div>
        <p>Error fetching data: {error.message}</p>
      </div>
    );
  }

  const taskHistory = useMemo(() => {
    const rows = data?.history ?? data?.running_tasks ?? [];
    return [...rows].sort((left, right) => {
      const leftDate = new Date(left?.started_at ?? left?.created_at ?? 0).getTime();
      const rightDate = new Date(
        right?.started_at ?? right?.created_at ?? 0,
      ).getTime();
      return rightDate - leftDate;
    });
  }, [data]);

  const paginatedRows = useMemo(() => {
    const startIndex = page * ROWS_PER_PAGE;
    return taskHistory.slice(startIndex, startIndex + ROWS_PER_PAGE);
  }, [page, taskHistory]);

  useEffect(() => {
    if (page > 0 && page * ROWS_PER_PAGE >= taskHistory.length) {
      setPage(0);
    }
  }, [page, taskHistory.length]);

  const handlePageChange = (_event, newPage) => {
    setPage(newPage);
  };

  const handleRowsPerPageChange = () => {};

  return (
    <div>
      <Box display="flex" alignItems="center" justifyContent="space-between">
        <h2>Tasks</h2>
        <Tooltip title="Refresh tasks">
          <span>
            <IconButton
              aria-label="Refresh tasks"
              onClick={() => refetch()}
              disabled={isFetching}
              size="small"
            >
              <RefreshIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Box>
      <TableContainer component={Paper} className="tasks-table-container">
        <Table className="responsive-table tasks-table" size="small" stickyHeader>
          <TableHead>
            <TableRow className="previous-log-row">
              <TableCell>ID</TableCell>
              <TableCell>Name</TableCell>
              <TableCell>Backend</TableCell>
              <TableCell>Owner</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Started At</TableCell>
              <TableCell>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="no-tasks">
                  <Box display="flex" alignItems="center" justifyContent="center">
                    <CircularProgress size={20} />
                    <Box component="span" ml={1}>
                      Loading
                    </Box>
                  </Box>
                </TableCell>
              </TableRow>
            ) : paginatedRows.length > 0 ? (
              paginatedRows.map((entry, index) => {
                const taskName =
                  entry?.task?.name ?? entry?.execution_request?.task ?? "Unknown";
                const taskBackend = entry?.task?.backend ?? "Unknown";
                const taskOwner = entry?.task?.owner ?? "Unknown";
                const status = entry?.status ?? "Unknown";
                const startedAt = entry?.started_at ?? entry?.created_at;
                const rowKey = entry?.id ?? `${taskName}-${index}`;

                return (
                  <TableRow key={rowKey}>
                    <TableCell>{entry?.id ?? ""}</TableCell>
                    <TableCell>{taskName}</TableCell>
                    <TableCell>{taskBackend}</TableCell>
                    <TableCell>{taskOwner}</TableCell>
                    <TableCell>
                      <Chip
                        label={status}
                        color={statusChipColor(status)}
                        size="small"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell className="relativeTime">
                      {formatDateTime(startedAt)}
                    </TableCell>
                    <TableCell>
                      {taskName !== "Unknown" ? (
                        <a href={`/tasks/${taskName}`}>
                          <span className="material-symbols-outlined">
                            visibility
                          </span>
                        </a>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })
            ) : (
              <TableRow className="previous-log-row">
                <TableCell colSpan={7} className="no-tasks">
                  No tasks found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <TablePagination
          component="div"
          count={taskHistory.length}
          page={page}
          onPageChange={handlePageChange}
          rowsPerPage={ROWS_PER_PAGE}
          onRowsPerPageChange={handleRowsPerPageChange}
          rowsPerPageOptions={[ROWS_PER_PAGE]}
        />
      </TableContainer>
    </div>
  );
};

const App = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <TasksTable />
    </QueryClientProvider>
  );
};

export default App;
