const path = require('path');

module.exports = {
  entry: {
    core: path.resolve(__dirname, 'frontend/core/index.js'),
    views: path.resolve(__dirname, 'frontend/views/index.js'),
  },
  output: {
    filename: '[name].bundle.js',
    path: path.resolve(__dirname, 'app/static/dist'),
    publicPath: '/static/dist/',
    clean: true,
  },
  optimization: {
    splitChunks: {
      chunks: 'all',
    },
  },
};
