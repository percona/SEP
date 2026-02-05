#!/bin/bash

set -e

echo "🔍 STARTING FAST AUDIT (STATIC ANALYSIS ONLY)..."
echo "================================================"

# 1. Security (Vulnerabilities)
echo "🛡️  Checking for known security flaws..."
pnpm audit --prod

# 2. Linting (Syntax & Quality)
echo ""
echo "🧹 Running Linter..."
# Checks if config exists before running to avoid crashing
if [ -f ".eslintrc.json" ] || [ -f "eslint.config.js" ]; then
    pnpm exec eslint .
else
    echo "⚠️  No ESLint config found. Skipping."
fi

# 3. Knip (Waste)
echo ""
echo "✂️  Checking for unused files..."
# We use a flag to ignore your 'static' folder issue from before
pnpm dlx knip --exclude static

echo ""
echo "✅ Static Analysis Complete! (Build verification skipped)"
