import { createRootRoute, createRoute, createRouter, redirect } from '@tanstack/react-router'

import { AppLayout } from '@/components/layout/AppLayout'
import { AdvisorPage } from '@/routes/advisor'
import { ByesPage } from '@/routes/byes'
import { ConnectPage } from '@/routes/connect'
import { TeamPage } from '@/routes/team'
import { TradePage } from '@/routes/trade'
import { useTeamStore } from '@/stores/team'

const rootRoute = createRootRoute({ component: AppLayout })

function requireTeam() {
  if (!useTeamStore.getState().team) throw redirect({ to: '/connect' })
}

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: () => {
    throw redirect({ to: useTeamStore.getState().team ? '/advisor' : '/connect' })
  },
})

const connectRoute = createRoute({ getParentRoute: () => rootRoute, path: '/connect', component: ConnectPage })
const advisorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/advisor',
  beforeLoad: requireTeam,
  component: AdvisorPage,
})
const teamRoute = createRoute({ getParentRoute: () => rootRoute, path: '/team', beforeLoad: requireTeam, component: TeamPage })
const byesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/byes', beforeLoad: requireTeam, component: ByesPage })
const tradeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/trade',
  beforeLoad: requireTeam,
  component: TradePage,
})

const routeTree = rootRoute.addChildren([indexRoute, connectRoute, advisorRoute, teamRoute, byesRoute, tradeRoute])

export const router = createRouter({ routeTree, defaultPreload: 'intent' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
