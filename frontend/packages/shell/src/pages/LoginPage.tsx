import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useForm, FormProvider } from 'react-hook-form';
import { TextInput } from '@percona/percona-ui';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CircularProgress from '@mui/material/CircularProgress';
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import axios from 'axios';
import { useAuth } from '../contexts/auth';

interface LoginFormValues {
  username: string;
  password: string;
}

/** Extract a user-friendly error message from the backend response */
function getErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status;
    const detail = err.response?.data?.detail;

    if (status === 401) {
      return detail || 'Invalid username or password.';
    }
    if (status === 403) {
      return detail || 'Your account is not active. Contact an administrator.';
    }
    if (detail) {
      return detail;
    }
  }
  return 'An unexpected error occurred. Please try again.';
}

export default function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const methods = useForm<LoginFormValues>({
    defaultValues: { username: '', password: '' },
  });

  const { handleSubmit, watch } = methods;

  const username = watch('username');
  const password = watch('password');

  const redirect = searchParams.get('redirect') || '/';

  const onSubmit = async (data: LoginFormValues) => {
    setError('');
    setLoading(true);

    try {
      await auth.login(data.username, data.password);
      navigate(redirect);
    } catch (err) {
      setError(getErrorMessage(err));
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

            <FormProvider {...methods}>
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
            </FormProvider>
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
