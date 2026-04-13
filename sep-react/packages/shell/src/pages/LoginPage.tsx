import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useForm, type Control, type FieldValues } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import axios from 'axios';
import { useAuth } from '../contexts/auth';

interface LoginFormValues {
  username: string;
  password: string;
}

/** True when the backend cannot handle the auth request (not running or route missing) */
function isBackendUnavailable(err: unknown): boolean {
  if (!axios.isAxiosError(err)) return false;
  if (err.code === 'ERR_NETWORK') return true;
  const status = err.response?.status;
  // 404 = route doesn't exist, 502/503 = upstream down
  return status === 404 || status === 502 || status === 503;
}

/** Extract a user-friendly error message from the backend response */
function getErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status;
    const detail = err.response?.data?.detail;

    if (status === 401) return detail || 'Invalid username or password.';
    if (status === 403) return detail || 'Your account is not active. Contact an administrator.';
    if (isBackendUnavailable(err)) return 'Backend is not available. You can sign in with mock mode.';
    if (detail) return detail;
  }
  return 'An unexpected error occurred. Please try again.';
}

export default function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [useMock, setUseMock] = useState(false);

  const { handleSubmit, watch, control } = useForm<LoginFormValues>({
    defaultValues: { username: '', password: '' },
  });

  const username = watch('username');
  const password = watch('password');

  const redirect = searchParams.get('redirect') || '/';

  const onSubmit = async (data: LoginFormValues) => {
    setError('');
    setLoading(true);

    try {
      if (useMock) {
        auth.mockLogin(data.username);
      } else {
        await auth.login(data.username, data.password);
      }
      navigate(redirect);
    } catch (err) {
      const msg = getErrorMessage(err);

      // If the backend can't handle auth, offer mock mode
      if (isBackendUnavailable(err)) {
        setUseMock(true);
      }

      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Container maxWidth="sm" sx={{ display: 'flex', alignItems: 'center', minHeight: '100vh' }}>
      <Box sx={{ width: '100%', maxWidth: 420, mx: 'auto' }}>
        <Card elevation={4} sx={{ borderRadius: 3, p: 2 }}>
          <CardContent>
            <Box sx={{ textAlign: 'center', pt: 2, pb: 1 }}>
              <Typography
                variant="h4"
                sx={{
                  fontFamily: '"Poppins", sans-serif',
                  fontWeight: 700,
                  color: 'primary.main',
                  mb: 0.5,
                }}
              >
                PERCONA
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Services Enablement Platform
              </Typography>
            </Box>

            <Box component="form" onSubmit={handleSubmit(onSubmit)} sx={{ mt: 3 }}>
              {error && (
                <Alert severity="error" onClose={() => setError('')} sx={{ mb: 2 }}>
                  {error}
                </Alert>
              )}

              <TextInput
                name="username"
                label="Username"
                isRequired
                control={control as unknown as Control<FieldValues>}
                textFieldProps={{
                  autoComplete: 'username',
                  fullWidth: true,
                }}
                controllerProps={{
                  rules: { required: 'Username is required' },
                }}
              />

              <TextInput
                name="password"
                label="Password"
                isRequired
                control={control as unknown as Control<FieldValues>}
                textFieldProps={{
                  type: 'password',
                  autoComplete: 'current-password',
                  fullWidth: true,
                }}
                controllerProps={{
                  rules: { required: 'Password is required' },
                }}
              />

              <Button
                type="submit"
                variant="contained"
                size="large"
                fullWidth
                disabled={!username || !password || loading}
                sx={{ mt: 2 }}
              >
                {loading ? <CircularProgress size={24} /> : 'Sign In'}
              </Button>
            </Box>

            {useMock && (
              <Box sx={{ textAlign: 'center', mt: 2 }}>
                <Chip
                  size="small"
                  color="warning"
                  variant="outlined"
                  icon={<InfoOutlinedIcon />}
                  label="Backend unreachable — mock mode enabled"
                />
              </Box>
            )}
          </CardContent>
        </Card>

        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', textAlign: 'center', mt: 3 }}
        >
          Percona LLC &copy; {new Date().getFullYear()}
        </Typography>
      </Box>
    </Container>
  );
}
