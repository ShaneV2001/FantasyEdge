import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { makeStaleTeamHandler } from '@/lib/stale-team'
import { router } from '@/router'
import './index.css'

const staleTeam = makeStaleTeamHandler(() => router.navigate({ to: '/connect' }))
const onStaleTeam = (err: unknown) => void staleTeam(err)

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onStaleTeam }),
  mutationCache: new MutationCache({ onError: onStaleTeam }),
  defaultOptions: {
    queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <RouterProvider router={router} />
        <Toaster theme="dark" richColors position="bottom-right" />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
