import { createRootRoute, createRoute, createRouter, redirect } from '@tanstack/react-router'

import { AppLayout } from '@/components/layout/AppLayout'
import { AdvisorPage } from '@/routes/advisor'
import { ByesPage } from '@/routes/byes'
import { ConnectPage } from '@/routes/connect'
import { BuyTargetsPage } from '@/routes/buy-targets'
import { PlayerPage } from '@/routes/player'
import { PlayersPage, playersSearchSchema } from '@/routes/players'
import { RankingsPage } from '@/routes/rankings'
import { SettingsPage } from '@/routes/settings'
import { TeamPage } from '@/routes/team'
import { TeamEditPage } from '@/routes/team-edit'
import { TradePage } from '@/routes/trade'
import { WaiversPage } from '@/routes/waivers'
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
const teamEditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/team/edit',
  beforeLoad: requireTeam,
  component: TeamEditPage,
})
const byesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/byes', beforeLoad: requireTeam, component: ByesPage })
const rankingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/rankings',
  beforeLoad: requireTeam,
  component: RankingsPage,
})
const buyTargetsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/buy-targets',
  beforeLoad: requireTeam,
  component: BuyTargetsPage,
})
const playersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/players',
  beforeLoad: requireTeam,
  validateSearch: (search) => playersSearchSchema.parse(search),
  component: PlayersPage,
})
const playerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/players/$playerId',
  beforeLoad: requireTeam,
  component: PlayerPage,
})
const tradeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/trade',
  beforeLoad: requireTeam,
  component: TradePage,
})
const waiversRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/waivers',
  beforeLoad: requireTeam,
  component: WaiversPage,
})
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/settings', component: SettingsPage })

const routeTree = rootRoute.addChildren([indexRoute, connectRoute, advisorRoute, teamRoute, teamEditRoute, byesRoute, rankingsRoute, buyTargetsRoute, playersRoute, playerRoute, tradeRoute, waiversRoute, settingsRoute])

export const router = createRouter({ routeTree, defaultPreload: 'intent' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
