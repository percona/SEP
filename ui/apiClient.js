import axios from 'axios';
import { Cookies } from 'react-cookie';

const cookies = new Cookies();

const apiClient = axios.create({
  baseURL: '/',
  withCredentials: true,
});




// Request Interceptor
apiClient.interceptors.request.use(
  (config) => {
    // Get the auth token from cookies
    const casdoorToken = cookies.get("casdoorToken");
    if (casdoorToken) {
      config.headers['Authorization'] = `Bearer ${casdoorToken}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

export default apiClient;