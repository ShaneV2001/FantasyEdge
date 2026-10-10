import type { CreateClientConfig } from '@/api/client.gen'

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: API_BASE,
})
