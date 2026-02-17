const path = require('path');
const fs = require('fs');

const pluginsDir = path.resolve(__dirname, 'templates');
const pluginsBuildDir = path.resolve(__dirname, 'static/plugins');
const SHARED_RUNTIME_CHUNK = 'shared/runtime';
const SHARED_MATERIAL_UI_CHUNK = 'shared/material-ui';
const entry = {};

// Find plugin directories that have a 'components' subdirectory
const pluginDirectories = fs.readdirSync(pluginsDir, { withFileTypes: true })
  .filter(dirent => dirent.isDirectory())
  .map(dirent => dirent.name)
  .filter(pluginName => fs.existsSync(path.join(pluginsDir, pluginName, 'components', 'main.js')));

// Create an entry point for each plugin
pluginDirectories.forEach(pluginName => {
  entry[pluginName] = path.join(pluginsDir, pluginName, 'components', 'main.js');
});

module.exports = {
  // Use the dynamically created entry object
  entry: entry,
  output: {
    filename: ({ chunk }) =>
      chunk.name && chunk.name.startsWith('shared/')
        ? `${chunk.name}.js`
        : `${chunk.name}/bundle.js`,
    chunkFilename: '[name].js',
    path: pluginsBuildDir,
    libraryTarget: 'umd',
    library: 'Plugin[name]',
  },
  module: {
    rules: [
      {
        test: /\.m?js$/,
        resolve: {
          fullySpecified: false,
        },
      },
      {
        test: /\.(js|jsx|tsx)$/,
        exclude: /node_modules/,
        use: {
          loader: 'babel-loader',
          options: {
            presets: ['@babel/preset-env', '@babel/preset-react'],
          },
        },
      },
    ],
  },
  resolve: {
    extensions: ['.js', '.jsx', '.tsx'],
    fullySpecified: false,
  },
  optimization: {
    runtimeChunk: {
      name: SHARED_RUNTIME_CHUNK,
    },
    splitChunks: {
      cacheGroups: {
        default: false,
        defaultVendors: false,
        materialUI: {
          name: SHARED_MATERIAL_UI_CHUNK,
          test: /[\\/]node_modules[\\/](?:@mui|@emotion)[\\/]/,
          chunks: 'all',
          enforce: true,
        },
      },
    },
  },
  performance: {
    hints: false, // Disables the warning entirely
    // OR
    maxEntrypointSize: 512000, // Raises limit to 512 KiB
    maxAssetSize: 512000,      // Raises limit to 512 KiB
  },
  plugins: [], 
};
