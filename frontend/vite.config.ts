import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          // Checked before the broad 'react' substring match below, since
          // that match also fires on 'react-leaflet' - without this, Leaflet
          // (only ever needed by the lazy-loaded Monitoring page) would ride
          // along in the vendor chunk every other page eagerly loads too.
          if (id.includes('leaflet')) return
          if (id.includes('react') || id.includes('react-dom') || id.includes('react-router')) {
            return 'react-vendor'
          }
        }
      }
    }
  }
})
