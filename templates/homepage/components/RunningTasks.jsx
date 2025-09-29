import React, { useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import apiClient from "../../../ui/apiClient";
import { format } from "date-fns";

// Create a client
const queryClient = new QueryClient();

// This function is now a pure JS function. It accepts cookies as an argument.
const fetchTasksHistory = async () => {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const { data } = await apiClient.get("/tasks/ui/history");
  return data;
};

// The main component that fetches and displays the data.
const RunningTasks = () => {
  const { data, error, isLoading } = useQuery({
    queryKey: ["running_tasks"],
    queryFn: () => fetchTasksHistory(),
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div>
        <span>Loading...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <p>Error fetching data: {error.message}</p>
      </div>
    );
  }

  if (!data || !data.running_tasks || data.running_tasks.length === 0) {
    return (
      <div>
        <h3>No running tasks found.</h3>
      </div>
    );
  }

  return (
    <div>
      <h2>Running Tasks</h2>
      <div className="tasks-table-container">
        <table className="responsive-table tasks-table">
          <thead>
            <tr className="previous-log-row">
              <th>ID</th>
              <th>Name</th>
              <th>Backend</th>
              <th>Owner</th>
              <th>Started At</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.running_tasks.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>{r.task.name}</td>
                <td>{r.task.backend}</td>
                <td>{r.task.owner}</td>
                <td className="relativeTime">{format(new Date(r.created_at), "yyyy-MM-dd HH:mm:ss")}</td>
                <td>
                   <a href={`/tasks/${r.task.name}`}><span class="material-symbols-outlined">visibility</span></a>
                </td> 
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// The root component that provides the QueryClient to the app.
const App = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <RunningTasks />
    </QueryClientProvider>
  );
};

export default App;