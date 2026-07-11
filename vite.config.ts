import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { cpSync, existsSync } from 'fs'
import { resolve } from 'path'

// Plugin: copy data/images/ → dist/data/images/ after each build so locally
// downloaded artist headshots are served alongside the static site.
// JSON snapshots are already inlined by import.meta.glob — no copy needed.
function copyDataImages() {
  return {
    name: 'copy-data-images',
    closeBundle() {
      const src  = resolve(__dirname, 'data/images')
      const dest = resolve(__dirname, 'dist/data/images')
      if (existsSync(src)) {
        cpSync(src, dest, { recursive: true })
      }
    },
  }
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    copyDataImages(),
  ],
  server: {
    port: 5174,
    // Serve data/images/ at /data/images/ during dev so local images work
    fs: { allow: ['..'] },
  },
})
