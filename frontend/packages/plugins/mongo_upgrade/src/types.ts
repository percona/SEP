export type MongoRole = 'primary' | 'secondary' | 'arbiter' | 'standalone' | 'unreachable';
export type DiscoveryStatus = 'pending' | 'running' | 'done' | 'failed';

export interface HostTopology {
  host_id: string;
  host_name: string | null;
  task_history_id: string;
  status: DiscoveryStatus;
  role: MongoRole | null;
  set_name: string | null;
  me: string | null;
  mongod_version: string | null;
}
