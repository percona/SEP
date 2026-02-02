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
import { createTheme, ThemeProvider } from "@mui/material/styles";
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

const getThemeModeFromDom = () => {
  if (typeof document === "undefined") {
    return "light";
  }

  const domTheme = document.body?.getAttribute("data-theme");
  if (domTheme === "dark" || domTheme === "light") {
    return domTheme;
  }

  const storedTheme =
    typeof window !== "undefined" ? window.localStorage?.getItem("theme") : null;
  if (storedTheme === "dark" || storedTheme === "light") {
    return storedTheme;
  }

  const prefersDark =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
};

const useDomThemeMode = () => {
  const [mode, setMode] = useState(getThemeModeFromDom);

  useEffect(() => {
    const body = document.body;
    if (!body) {
      return undefined;
    }

    const updateMode = () => {
      const nextMode =
        body.getAttribute("data-theme") === "dark" ? "dark" : "light";
      setMode(nextMode);
    };

    updateMode();

    const observer = new MutationObserver(updateMode);
    observer.observe(body, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => observer.disconnect();
  }, []);

  return mode;
};

const buildTheme = (mode) => {
  const styles =
    typeof document !== "undefined" ? getComputedStyle(document.body) : null;
  const getVar = (name, fallback) => {
    if (!styles) {
      return fallback;
    }
    const value = styles.getPropertyValue(name);
    return value ? value.trim() : fallback;
  };

  return createTheme({
    palette: {
      mode,
      primary: {
        main: getVar("--primaryMain", "#1976d2"),
        light: getVar("--primaryLight", "#42a5f5"),
        dark: getVar("--primaryDark", "#1565c0"),
        contrastText: getVar("--primaryContrast", "#ffffff"),
      },
      secondary: {
        main: getVar("--lineFocus", "#0288d1"),
        light: getVar("--lineFocus", "#03a9f4"),
        dark: getVar("--lineFocus", "#0277bd"),
        contrastText: getVar("--textPrimary", "#ffffff"),
      },
      success: {
        main: getVar("--successMain", "#2e7d32"),
        light: getVar("--successLight", "#60ad5e"),
        dark: getVar("--successDark", "#1b5e20"),
        contrastText: getVar("--successContrast", "#ffffff"),
      },
      error: {
        main: getVar("--errorMain", "#d32f2f"),
        light: getVar("--errorLight", "#ef5350"),
        dark: getVar("--errorDark", "#c62828"),
        contrastText: getVar("--errorContrast", "#ffffff"),
      },
      info: {
        main: getVar("--lineFocus", "#0288d1"),
        light: getVar("--lineFocus", "#03a9f4"),
        dark: getVar("--lineFocus", "#0277bd"),
        contrastText: getVar("--textPrimary", "#ffffff"),
      },
      warning: {
        main: getVar("--primaryLight", "#ed6c02"),
        light: getVar("--primaryLight", "#ff9800"),
        dark: getVar("--primaryDark", "#e65100"),
        contrastText: getVar("--primaryContrast", "#ffffff"),
      },
      text: {
        primary: getVar("--textPrimary", "#111111"),
        secondary: getVar("--textSecondary", "#555555"),
        disabled: getVar("--textDisabled", "#9e9e9e"),
      },
      divider: getVar("--lineDivider", "rgba(0, 0, 0, 0.12)"),
      background: {
        default: getVar("--surfaceElevation0", "#ffffff"),
        paper: getVar("--surfaceElevation1", "#ffffff"),
      },
      action: {
        hover: getVar("--actionHover", "rgba(0, 0, 0, 0.04)"),
        disabled: getVar("--actionDisabled", "rgba(0, 0, 0, 0.26)"),
        focus: getVar("--actionFocus", "rgba(0, 0, 0, 0.12)"),
      },
    },
    typography: {
      fontFamily: "'Roboto', sans-serif",
    },
    components: {
      MuiTableCell: {
        styleOverrides: {
          root: {
            borderBottomColor: "var(--lineDivider)",
          },
          head: {
            fontWeight: 600,
          },
        },
      },
    },
  });
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
  const mode = useDomThemeMode();
  const theme = useMemo(() => buildTheme(mode), [mode]);

  return (
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={queryClient}>
        <TasksTable />
      </QueryClientProvider>
    </ThemeProvider>
  );
};

export default App;
