#!/bin/sh
set -eu

cd /home/node/work/dashboard
node ../offline-npm-lock.mjs package-lock.json ../frontend-artifacts.json ../tarballs
npm ci --offline --ignore-scripts
node --input-type=module -e 'await import("vite"); await import("react"); await import("remotion")'
npm run build
test -s dist/index.html
printf 'MEMORY_PEAK_BYTES='
cat /sys/fs/cgroup/memory.peak
