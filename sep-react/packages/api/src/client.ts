import axios from 'axios';
import applyCaseMiddleware from 'axios-case-converter';

/**
 * Primary API client with automatic camelCase <-> snake_case conversion.
 * All SEP API requests go through this client.
 */
export const apiClient = applyCaseMiddleware(
  axios.create({
    baseURL: '/api',
    headers: {
      'Content-Type': 'application/json',
    },
    // Backend returns 303 for expired sessions — don't auto-follow redirects
    maxRedirects: 0,
    validateStatus: (status) => status >= 200 && status < 300,
  }),
);

// Attach Bearer token from localStorage on every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('sep_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 and 303 globally — clear token and redirect to login
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      // 401 = invalid token, 303 = session expired (backend redirect to login)
      if (status === 401 || status === 303) {
        localStorage.removeItem('sep_token');
        localStorage.removeItem('sep_refresh_token');
        // Only redirect if not already on login page (avoid loops)
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
        }
      }
    }
    return Promise.reject(error);
  },
);
