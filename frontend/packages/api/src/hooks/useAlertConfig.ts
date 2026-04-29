import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../client';

/** Shape returned by `GET /api/config/alerts`. */
export interface AlertConfig {
  available: boolean;
}

export const ALERT_CONFIG_QUERY_KEY = ['config', 'alerts'] as const;

/**
 * Fetches whether at least one alert provider is configured on the backend
 * (`bool(alert_settings.PROVIDERS)`). Used by `<AlertOnFailField>` to decide
 * if the *Alert on failure* checkbox should be enabled.
 *
 * The result rarely changes within a session, so it's cached for 5 minutes.
 */
export function useAlertConfig() {
  return useQuery<AlertConfig>({
    queryKey: ALERT_CONFIG_QUERY_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<AlertConfig>('/config/alerts');
      return data;
    },
    staleTime: 5 * 60 * 1000,
  });
}
