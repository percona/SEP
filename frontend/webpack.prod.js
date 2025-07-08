const {
    merge
} = require("webpack-merge");
const common = require("./webpack.config.js");
const path = require("path");
const {
    WebpackManifestPlugin
} = require("webpack-manifest-plugin");

module.exports = merge(common, {
    mode: "production",
    output: {
        path: path.resolve(__dirname, "../static/react"),
        filename: "[name].[contenthash].js",
        publicPath: "/static/react/",
        clean: true,
    },
    optimization: {
        splitChunks: {
            chunks: "all",
            cacheGroups: {
                vendor: {
                    test: /[\\/]node_modules[\\/]/,
                    name: "vendors",
                    chunks: "all",
                },
            },
        },
    },
    plugins: [
        new WebpackManifestPlugin({
            fileName: "asset-manifest.json",
            publicPath: "/static/react/",
        }),
    ],
    devtool: "source-map",
});
