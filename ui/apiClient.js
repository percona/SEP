import axios from 'axios';
import { Cookies } from 'react-cookie'; // Using react-cookie to get the token

const cookies = new Cookies();

const apiClient = axios.create({
  baseURL: '/', // Your API base URL
  withCredentials: true,
});

// Request Interceptor
apiClient.interceptors.request.use(
  (config) => {
    // Get the token from cookies
    const casdoorToken = cookies.get("casdoorToken");

    // If the token exists, add it to the Authorization header
    if (casdoorToken) {
      config.headers['Authorization'] = `Bearer ${casdoorToken}`;
    }

    // Return the modified configuration
    return config;
  },
  (error) => {
    // Do something with request error
    return Promise.reject(error);
  }
);

export default apiClient;
