const path = require('path');
const fs = require('fs');

const pluginsDir = path.resolve(__dirname, 'templates');
const pluginsBuildDir = path.resolve(__dirname, 'static/plugins');
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
    // The [name] placeholder will be replaced by the key from the 'entry' object (e.g., 'plugin_one')
    filename: '[name]/bundle.js', 
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
            presets: ['@babel/preset-env', '@babel/preset-react', '@babel/preset-typescript'],
          },
        },
      },
    ],
  },
  resolve: {
    extensions: ['.js', '.jsx', '.tsx'],
    fullySpecified: false,
  },
  // The 'plugins' array is left empty because we don't need HtmlWebpackPlugin
  plugins: [], 
};
