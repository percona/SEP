const path = require('path');
const fs = require('fs');
const HtmlWebpackPlugin = require('html-webpack-plugin'); // Import the plugin

const pluginsDir = path.resolve(__dirname, 'templates');
const pluginsBuildDir = path.resolve(__dirname, 'static/plugins');
const entry = {};
const htmlPlugins = []; // Array to store HtmlWebpackPlugin instances

// Find plugin directories
const pluginDirectories = fs.readdirSync(pluginsDir, { withFileTypes: true })
  .filter(dirent => dirent.isDirectory())
  .map(dirent => dirent.name)
  .filter(pluginName => fs.existsSync(path.join(pluginsDir, pluginName, 'components')));

// Create entry points and HTML plugins for each plugin
pluginDirectories.forEach(pluginName => {
  const pluginPath = path.join(pluginsDir, pluginName);
  entry[pluginName] = path.join(pluginPath, 'components', 'index.js');

  // Create an HTMLWebpackPlugin instance for each entry
  htmlPlugins.push(
    new HtmlWebpackPlugin({
      template: path.join(pluginPath, 'components', 'index.html'), // Assuming each plugin has its own template
      filename: `${pluginName}/index.html`, // Output filename for the HTML
      chunks: [pluginName], // This is key: it injects only the specific bundle
      inject: 'body', // Injects the script tag into the body
    })
  );
});

module.exports = {
  entry: entry,
  output: {
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
  plugins: htmlPlugins, // Add the array of plugins here
};
