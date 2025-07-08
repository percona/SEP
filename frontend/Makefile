.PHONY: install dev build clean

# Install dependencies
install:
	npm install

# Start development server
dev:
	npm run dev

# Build for production
build:
	npm run build

# Clean build artifacts
clean:
	rm -rf dist
	rm -rf ../static/react

# Install and build for production
setup: install build

# Watch and rebuild on changes
watch:
	npm run build:dev -- --watch

# Development with hot reload
start:
	npm start
