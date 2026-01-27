import React from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
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

const TasksTable = () => {
  const { data, error, isLoading } = useQuery({
    queryKey: ["tasks_history"],
    queryFn: fetchTasksHistory,
    refetchInterval: 10000,
  });

  if (error) {
    return (
      <div>
        <p>Error fetching data: {error.message}</p>
      </div>
    );
  }

  const taskHistory = data?.history ?? data?.running_tasks ?? [];

  return (
    <div>
      <h2>Tasks</h2>
      <div className="tasks-table-container">
        <table className="responsive-table tasks-table">
          <thead>
            <tr className="previous-log-row">
              <th>ID</th>
              <th>Name</th>
              <th>Backend</th>
              <th>Owner</th>
              <th>Status</th>
              <th>Started At</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan="7" className="no-tasks">
                  Loading
                </td>
              </tr>
            ) : taskHistory.length > 0 ? (
              taskHistory.map((entry, index) => {
                const taskName =
                  entry?.task?.name ?? entry?.execution_request?.task ?? "Unknown";
                const taskBackend = entry?.task?.backend ?? "Unknown";
                const taskOwner = entry?.task?.owner ?? "Unknown";
                const status = entry?.status ?? "Unknown";
                const startedAt = entry?.started_at ?? entry?.created_at;
                const rowKey = entry?.id ?? `${taskName}-${index}`;

                return (
                  <tr key={rowKey}>
                    <td>{entry?.id ?? ""}</td>
                    <td>{taskName}</td>
                    <td>{taskBackend}</td>
                    <td>{taskOwner}</td>
                    <td>{status}</td>
                    <td className="relativeTime">{formatDateTime(startedAt)}</td>
                    <td>
                      {taskName !== "Unknown" ? (
                        <a href={`/tasks/${taskName}`}>
                          <span className="material-symbols-outlined">
                            visibility
                          </span>
                        </a>
                      ) : null}
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr className="previous-log-row">
                <td colSpan="7" className="no-tasks">
                  No tasks found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
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
