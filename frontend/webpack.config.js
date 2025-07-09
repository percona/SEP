const HtmlWebpackPlugin = require("html-webpack-plugin");
const ModuleFederationPlugin = require("webpack/lib/container/ModuleFederationPlugin");
const path = require("path");

module.exports = {
    entry: "./src/bootstrap.js",
    output: {
        path: path.resolve(__dirname, "dist"),
        filename: "[name].[contenthash].js",
        publicPath: "auto",
        clean: true,
    },
    resolve: {
        extensions: [".js", ".jsx", ".ts", ".tsx"],
        alias: {
            // Ensure React is properly resolved
            'react': path.resolve('./node_modules/react'),
            'react-dom': path.resolve('./node_modules/react-dom'),
        },
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
            exposes: {
                "./RemoteComponent": "./src/components/RemoteComponent.jsx",
            },
            shared: {
                react: {
                    singleton: true,
                    requiredVersion: false,
                    eager: true,
                },
                "react-dom": {
                    singleton: true,
                    requiredVersion: false,
                    eager: true,
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
