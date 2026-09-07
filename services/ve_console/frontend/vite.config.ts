import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Served by ve_console (FastAPI) under /app — see main.py's static mount +
// catch-all route. base must match that mount path so built asset URLs
// (JS/CSS chunk references inside index.html) resolve correctly; outDir
// puts the build where the Python package can find it without needing
// anything installed outside this image's own build context.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: {
    outDir: '../src/ve_console/react_dist',
    emptyOutDir: true,
  },
})
