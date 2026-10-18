import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Windows 下部分安全策略/沙箱会阻止 esbuild 子进程删除系统临时目录中的文件，
// 导致打包大 chunk（>1MB）时报 "remove ...: Access is denied."。
// 将 esbuild 使用的临时目录固定到项目内（node_modules 已被 git 忽略）。
if (process.platform === 'win32') {
  try {
    const tempDir = resolve(process.cwd(), 'node_modules/.cache/vite-tmp')
    mkdirSync(tempDir, { recursive: true })
    process.env.TMP = tempDir
    process.env.TEMP = tempDir
  } catch {
    // 无法创建项目内临时目录时回退到系统默认临时目录
  }
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.EDURAGE_API_PROXY ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    globals: true,
  },
} as any)
