import { defineConfig } from '@hey-api/openapi-ts'

export default defineConfig({
  input: './openapi.json',
  output: { path: 'src/api' },
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
    { name: '@hey-api/client-fetch', runtimeConfigPath: '@/lib/api-config' },
    '@tanstack/react-query',
  ],
})
