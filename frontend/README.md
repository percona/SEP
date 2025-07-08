# SEP Frontend with Module Federation

This directory contains the React frontend application that integrates with the FastAPI backend using Webpack Module Federation.

## Features

- **Module Federation**: Allows sharing React components between applications
- **React 18**: Modern React with hooks and functional components
- **Webpack 5**: Latest webpack with Module Federation support
- **Simple Setup**: Minimal React app ready for expansion
- **API Integration**: Seamless communication with FastAPI backend

## Setup

### Prerequisites

- Node.js 18+
- npm

### Installation

```bash
# Install dependencies
npm install

# Build for production (outputs to ../static/react/)
npm run build

# Start development server
npm run dev
```

### Development

```bash
# Start development server with hot reload
npm start

# Build in development mode
npm run build:dev

# Watch for changes and rebuild
npm run watch
```

## Integration with FastAPI

The React app is integrated with your FastAPI backend through:

1. **Static Files**: Built React files are served from `/static/react/`
2. **API Endpoints**: React components communicate with FastAPI APIs
3. **Template Integration**: React app loads in Jinja2 templates

### Accessing the React App

- **Development**: `http://localhost:3000` (webpack dev server)
- **Production**: `http://localhost:8000/react` (integrated with FastAPI)

## Module Federation

### Exposed Components

The following components are exposed for use by other applications:

- `./ReactApp`: Main React application

## Building for Production

```bash
# Build optimized production bundle
npm run build

# Files will be output to ../static/react/
# These are automatically served by FastAPI
```

## Development Workflow

1. **Start FastAPI backend**: `python3 -m app.main`
2. **Start React dev server**: `npm start`
3. **Make changes** to React components
4. **Build for production**: `npm run build`
5. **Test integration**: Visit `http://localhost:8000/react`

## File Structure

```
frontend/
├── src/
│   ├── components/          # React components (ready for expansion)
│   ├── App.jsx             # Main app component
│   ├── App.css             # App styles
│   ├── index.js            # Entry point
│   └── bootstrap.js        # Module Federation bootstrap
├── public/
│   └── index.html          # HTML template
├── webpack.config.js       # Webpack configuration
├── webpack.prod.js         # Production webpack config
├── package.json            # Dependencies and scripts
└── README.md              # This file
```

## Current State

This is a minimal React application with:
- Basic "Hello World" component
- Webpack Module Federation setup
- Ready for component expansion
- Integration with FastAPI backend

## Troubleshooting

### Module Federation Issues

If components don't load:
1. Check that `remoteEntry.js` is accessible
2. Verify webpack configuration
3. Check browser console for errors

### API Communication Issues

If API calls fail:
1. Verify FastAPI backend is running
2. Check CORS configuration
3. Ensure authentication is working

### Build Issues

If build fails:
1. Clear node_modules: `rm -rf node_modules && npm install`
2. Clear build cache: `rm -rf dist && npm run build`
3. Check webpack configuration

## Contributing

1. Follow React best practices
2. Use functional components with hooks
3. Maintain responsive design
4. Test API integration
5. Update documentation
