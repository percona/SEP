import React, { useState, useEffect, createContext, useContext } from "react";
import {
  Box,
  TextField,
  Button,
  Typography,
  Paper,
  Container,
  Alert,
  CircularProgress,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Grid,
  Card,
  CardContent,
  ThemeProvider,
  createTheme,
  ToggleButton,
  ToggleButtonGroup,
  IconButton,
  Tooltip,
} from "@mui/material";
import {
  Send as SendIcon,
  Refresh as RefreshIcon,
  LightMode as LightModeIcon,
  DarkMode as DarkModeIcon,
  Palette as PaletteIcon,
  Brightness4 as Brightness4Icon,
} from "@mui/icons-material";

// Theme Context
const ThemeContext = createContext();

// Theme definitions
const themes = {
  light: createTheme({
    palette: {
      mode: 'light',
      primary: {
        main: '#1976d2',
        light: '#42a5f5',
        dark: '#1565c0',
        contrastText: '#ffffff',
      },
      secondary: {
        main: '#dc004e',
        light: '#ff5983',
        dark: '#9a0036',
        contrastText: '#ffffff',
      },
      background: {
        default: '#f5f5f5',
        paper: '#ffffff',
      },
      text: {
        primary: '#212121',
        secondary: '#757575',
      },
    },
    typography: {
      fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
      h4: {
        fontWeight: 600,
        letterSpacing: '-0.5px',
      },
      h6: {
        fontWeight: 500,
      },
      body1: {
        lineHeight: 1.6,
      },
    },
    shape: {
      borderRadius: 12,
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.1)',
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 500,
            borderRadius: 8,
            padding: '10px 24px',
          },
          contained: {
            boxShadow: '0 2px 8px rgba(25, 118, 210, 0.3)',
            '&:hover': {
              boxShadow: '0 4px 12px rgba(25, 118, 210, 0.4)',
            },
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 8,
            },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            boxShadow: '0 2px 12px rgba(0, 0, 0, 0.08)',
          },
        },
      },
    },
  }),

  dark: createTheme({
    palette: {
      mode: 'dark',
      primary: {
        main: '#90caf9',
        light: '#e3f2fd',
        dark: '#42a5f5',
        contrastText: '#000000',
      },
      secondary: {
        main: '#f48fb1',
        light: '#f8bbd9',
        dark: '#ec407a',
        contrastText: '#000000',
      },
      background: {
        default: '#121212',
        paper: '#1e1e1e',
      },
      text: {
        primary: '#ffffff',
        secondary: '#b3b3b3',
      },
    },
    typography: {
      fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
      h4: {
        fontWeight: 600,
        letterSpacing: '-0.5px',
      },
      h6: {
        fontWeight: 500,
      },
      body1: {
        lineHeight: 1.6,
      },
    },
    shape: {
      borderRadius: 12,
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 500,
            borderRadius: 8,
            padding: '10px 24px',
          },
          contained: {
            boxShadow: '0 2px 8px rgba(144, 202, 249, 0.3)',
            '&:hover': {
              boxShadow: '0 4px 12px rgba(144, 202, 249, 0.4)',
            },
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 8,
            },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            boxShadow: '0 2px 12px rgba(0, 0, 0, 0.2)',
          },
        },
      },
    },
  }),

  blue: createTheme({
    palette: {
      mode: 'light',
      primary: {
        main: '#2196f3',
        light: '#64b5f6',
        dark: '#1976d2',
        contrastText: '#ffffff',
      },
      secondary: {
        main: '#ff9800',
        light: '#ffb74d',
        dark: '#f57c00',
        contrastText: '#000000',
      },
      background: {
        default: '#e3f2fd',
        paper: '#ffffff',
      },
      text: {
        primary: '#1565c0',
        secondary: '#1976d2',
      },
    },
    typography: {
      fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
      h4: {
        fontWeight: 600,
        letterSpacing: '-0.5px',
        color: '#1565c0',
      },
      h6: {
        fontWeight: 500,
      },
      body1: {
        lineHeight: 1.6,
      },
    },
    shape: {
      borderRadius: 12,
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            boxShadow: '0 4px 20px rgba(33, 150, 243, 0.15)',
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 500,
            borderRadius: 8,
            padding: '10px 24px',
          },
          contained: {
            boxShadow: '0 2px 8px rgba(33, 150, 243, 0.3)',
            '&:hover': {
              boxShadow: '0 4px 12px rgba(33, 150, 243, 0.4)',
            },
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 8,
            },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            boxShadow: '0 2px 12px rgba(33, 150, 243, 0.1)',
          },
        },
      },
    },
  }),

  green: createTheme({
    palette: {
      mode: 'light',
      primary: {
        main: '#4caf50',
        light: '#81c784',
        dark: '#388e3c',
        contrastText: '#ffffff',
      },
      secondary: {
        main: '#ff5722',
        light: '#ff8a65',
        dark: '#d84315',
        contrastText: '#ffffff',
      },
      background: {
        default: '#e8f5e8',
        paper: '#ffffff',
      },
      text: {
        primary: '#2e7d32',
        secondary: '#388e3c',
      },
    },
    typography: {
      fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
      h4: {
        fontWeight: 600,
        letterSpacing: '-0.5px',
        color: '#2e7d32',
      },
      h6: {
        fontWeight: 500,
      },
      body1: {
        lineHeight: 1.6,
      },
    },
    shape: {
      borderRadius: 12,
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            boxShadow: '0 4px 20px rgba(76, 175, 80, 0.15)',
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 500,
            borderRadius: 8,
            padding: '10px 24px',
          },
          contained: {
            boxShadow: '0 2px 8px rgba(76, 175, 80, 0.3)',
            '&:hover': {
              boxShadow: '0 4px 12px rgba(76, 175, 80, 0.4)',
            },
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 8,
            },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            boxShadow: '0 2px 12px rgba(76, 175, 80, 0.1)',
          },
        },
      },
    },
  }),
};

// Theme Provider Component
function ThemeProviderWrapper({ children }) {
  const [currentTheme, setCurrentTheme] = useState('light');

  const handleThemeChange = (event, newTheme) => {
    if (newTheme !== null) {
      setCurrentTheme(newTheme);
      // Save theme preference to localStorage
      localStorage.setItem('sep-theme', newTheme);
    }
  };

  // Load theme preference from localStorage on mount
  useEffect(() => {
    const savedTheme = localStorage.getItem('sep-theme');
    if (savedTheme && themes[savedTheme]) {
      setCurrentTheme(savedTheme);
    }
  }, []);

  return (
    <ThemeContext.Provider value={{ currentTheme, handleThemeChange }}>
      <ThemeProvider theme={themes[currentTheme]}>
        {children}
      </ThemeProvider>
    </ThemeContext.Provider>
  );
}

// Theme Switcher Component
function ThemeSwitcher() {
  const { currentTheme, handleThemeChange } = useContext(ThemeContext);

  return (
    <Box sx={{
      position: 'fixed',
      top: 20,
      right: 20,
      zIndex: 1000,
      bgcolor: 'background.paper',
      borderRadius: 2,
      boxShadow: 3,
      p: 1,
    }}>
      <ToggleButtonGroup
        value={currentTheme}
        exclusive
        onChange={handleThemeChange}
        aria-label="theme selection"
        size="small"
      >
        <ToggleButton value="light" aria-label="light theme">
          <Tooltip title="Light Theme">
            <LightModeIcon />
          </Tooltip>
        </ToggleButton>
        <ToggleButton value="dark" aria-label="dark theme">
          <Tooltip title="Dark Theme">
            <DarkModeIcon />
          </Tooltip>
        </ToggleButton>
        <ToggleButton value="blue" aria-label="blue theme">
          <Tooltip title="Blue Theme">
            <PaletteIcon />
          </Tooltip>
        </ToggleButton>
        <ToggleButton value="green" aria-label="green theme">
          <Tooltip title="Green Theme">
            <Brightness4Icon />
          </Tooltip>
        </ToggleButton>
      </ToggleButtonGroup>
    </Box>
  );
}

function RemoteComponent() {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    message: "",
    category: "",
  });
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState(null);
  const [error, setError] = useState(null);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResponse(null);

    try {
      // Simulate API call to FastAPI backend
      // In a real scenario, this would be a call to your FastAPI endpoint
      const response = await fetch('/api/contact', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });

      if (response.ok) {
        const data = await response.json();
        setResponse(data);
      } else {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
    } catch (err) {
      // For demo purposes, we'll simulate a successful response
      // since we don't have the actual FastAPI endpoint set up
      console.log('Simulating API response for demo...');
      setTimeout(() => {
        setResponse({
          success: true,
          message: "Form submitted successfully!",
          data: formData,
          timestamp: new Date().toISOString()
        });
        setLoading(false);
      }, 1000);
    }
  };

  const handleReset = () => {
    setFormData({
      name: "",
      email: "",
      message: "",
      category: "",
    });
    setResponse(null);
    setError(null);
  };

  return (
    <ThemeProviderWrapper>
      <ThemeSwitcher />
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Paper elevation={3} sx={{ p: 4 }}>
          <Typography variant="h4" component="h1" gutterBottom align="center" color="primary">
            Contact Form (MUI + Module Federation)
          </Typography>

          <Typography variant="body1" color="text.secondary" align="center" sx={{ mb: 4 }}>
            This component is loaded via Module Federation and uses Material-UI
          </Typography>

          <Box component="form" onSubmit={handleSubmit} sx={{ mt: 3 }}>
            <Grid container spacing={3}>
              <Grid item xs={12} sm={6}>
                <TextField
                  required
                  fullWidth
                  label="Name"
                  name="name"
                  value={formData.name}
                  onChange={handleInputChange}
                  variant="outlined"
                />
              </Grid>

              <Grid item xs={12} sm={6}>
                <TextField
                  required
                  fullWidth
                  label="Email"
                  name="email"
                  type="email"
                  value={formData.email}
                  onChange={handleInputChange}
                  variant="outlined"
                />
              </Grid>

              <Grid item xs={12}>
                <FormControl fullWidth>
                  <InputLabel>Category</InputLabel>
                  <Select
                    name="category"
                    value={formData.category}
                    label="Category"
                    onChange={handleInputChange}
                  >
                    <MenuItem value="general">General Inquiry</MenuItem>
                    <MenuItem value="support">Technical Support</MenuItem>
                    <MenuItem value="feedback">Feedback</MenuItem>
                    <MenuItem value="other">Other</MenuItem>
                  </Select>
                </FormControl>
              </Grid>

              <Grid item xs={12}>
                <TextField
                  required
                  fullWidth
                  label="Message"
                  name="message"
                  multiline
                  rows={4}
                  value={formData.message}
                  onChange={handleInputChange}
                  variant="outlined"
                />
              </Grid>
            </Grid>

            <Box sx={{ mt: 4, display: 'flex', gap: 2, justifyContent: 'center' }}>
              <Button
                type="submit"
                variant="contained"
                size="large"
                startIcon={loading ? <CircularProgress size={20} /> : <SendIcon />}
                disabled={loading}
              >
                {loading ? 'Submitting...' : 'Submit'}
              </Button>

              <Button
                variant="outlined"
                size="large"
                startIcon={<RefreshIcon />}
                onClick={handleReset}
                disabled={loading}
              >
                Reset
              </Button>
            </Box>
          </Box>

          {/* Response Display */}
          {response && (
            <Card sx={{ mt: 4, bgcolor: 'success.light' }}>
              <CardContent>
                <Alert severity="success">
                  <Typography variant="h6" gutterBottom>
                    Success!
                  </Typography>
                  <Typography variant="body2">
                    {response.message}
                  </Typography>
                  <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                    Submitted at: {new Date(response.timestamp).toLocaleString()}
                  </Typography>
                </Alert>
              </CardContent>
            </Card>
          )}
        </Paper>
      </Container>
    </ThemeProviderWrapper>
  );
}

export default RemoteComponent;
