import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRootRoute, createRouter } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'

import { TooltipProvider } from '@/components/ui/tooltip'

/** Render a page with React Query, tooltips and a router (so <Link>s work), at `url`. */
export function renderPage(ui: ReactElement, url = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        <TooltipProvider>{ui}</TooltipProvider>
      </QueryClientProvider>
    ),
  })
  const router = createRouter({ routeTree: rootRoute, history: createMemoryHistory({ initialEntries: [url] }) })
  return render(<RouterProvider router={router} />)
}
