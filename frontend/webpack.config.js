const HtmlWebpackPlugin = require("html-webpack-plugin");
const ModuleFederationPlugin = require("webpack/lib/container/ModuleFederationPlugin");
const path = require("path");

module.exports = {
    entry: "./src/index.js",
    output: {
        path: path.resolve(__dirname, "dist"),
        filename: "[name].[contenthash].js",
        publicPath: "auto",
        clean: true,
    },
    resolve: {
        extensions: [".js", ".jsx", ".ts", ".tsx"],
    },
    module: {
        rules: [{
            test: /\.(js|jsx|ts|tsx)$/,
            exclude: /node_modules/,
            use: {
                loader: "babel-loader",
                options: {
                    presets: [
                        "@babel/preset-env",
                        ["@babel/preset-react", {
                            runtime: "automatic"
                        }],
                    ],
                },
            },
        }, {
            test: /\.css$/,
            use: ["style-loader", "css-loader"],
        }, {
            test: /\.(png|svg|jpg|jpeg|gif)$/i,
            type: "asset/resource",
        }, ],
    },
    plugins: [
        new ModuleFederationPlugin({
            name: "sep_host",
            filename: "remoteEntry.js",
            remotes: {
                // You can add remote modules here when needed
                // sep_remote: "sep_remote@http://localhost:3001/remoteEntry.js",
            },
            exposes: {
                // Expose the main React app
                "./ReactApp": "./src/ReactApp.js",
                "./App": "./src/ReactApp.js",
            },
            shared: {
                react: {
                    singleton: true,
                    requiredVersion: "^18.2.0",
                },
                "react-dom": {
                    singleton: true,
                    requiredVersion: "^18.2.0",
                },
            },
        }),
        new HtmlWebpackPlugin({
            template: "./public/index.html",
        }),
    ],
    devServer: {
        port: 3000,
        hot: true,
        historyApiFallback: true,
        headers: {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "X-Requested-With, content-type, Authorization",
        },
    },
};
