import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { useEffect } from 'react'
import { ArrowLeftRight, CalendarRange, ClipboardPlus, CloudDownload, Crosshair, LayoutList, ListOrdered, Plug, RefreshCw, Settings2, Sparkles, Swords, UserSearch, Users } from 'lucide-react'
import { toast } from 'sonner'

import { getTeamOptions, refreshMutation } from '@/api/@tanstack/react-query.gen'
import { Button } from '@/components/ui/button'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'
import { TeamSwitcher } from '@/components/layout/TeamSwitcher'
import { nflSyncedAt, useNflRefresh, useStatus } from '@/components/layout/DataFreshness'
import { useTradeOffers } from '@/components/trade/TradeOffers'
import { describeError } from '@/lib/errors'
import { fmtRelative } from '@/lib/format'
import { useTeamStore } from '@/stores/team'

const NAV = [
  { to: '/advisor', label: 'Advisor', icon: Sparkles },
  { to: '/team', label: 'My Team', icon: Users },
  { to: '/startsit', label: 'Start/Sit', icon: LayoutList },
  { to: '/matchup', label: 'Matchup', icon: Swords },
  { to: '/byes', label: 'Byes', icon: CalendarRange },
  { to: '/players', label: 'Players', icon: UserSearch },
  { to: '/rankings', label: 'Rankings', icon: ListOrdered },
  { to: '/buy-targets', label: 'Buy targets', icon: Crosshair },
  { to: '/trade', label: 'Trade', icon: ArrowLeftRight },
  { to: '/waivers', label: 'Waivers', icon: ClipboardPlus },
] as const

export function AppSidebar() {
  const team = useTeamStore((s) => s.team)
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  // On phones the sidebar is a slide-over sheet that locks the page while open: close it whenever
  // you navigate (or tap the page you're already on), so the page underneath scrolls again.
  const { isMobile, setOpenMobile } = useSidebar()
  const closeOnPhone = () => {
    if (isMobile) setOpenMobile(false)
  }
  useEffect(() => {
    setOpenMobile(false)
  }, [pathname, setOpenMobile])
  const qc = useQueryClient()
  const navigate = useNavigate()
  const teamQuery = useQuery({
    ...getTeamOptions({ path: { team_id: team?.teamId ?? '' } }),
    enabled: !!team,
  })
  const refresh = useMutation({
    ...refreshMutation(),
    onSuccess: (res) => {
      toast.success('Roster refreshed', { description: res.detail.join(' · ') })
      void qc.invalidateQueries()
    },
    onError: (err) => {
      const p = describeError(err)
      toast.error(p.message, {
        description: p.hint,
        action: p.action ? { label: p.action.label, onClick: () => void navigate(p.action!) } : undefined,
      })
    },
  })
  const league = teamQuery.data?.league
  const offers = useTradeOffers(team)
  const status = useStatus()
  const nfl = useNflRefresh()
  const nflBusy = nfl.isPending || !!status.data?.data_refreshing
  const badges: Partial<Record<(typeof NAV)[number]['to'], number>> = { '/trade': offers.data?.received.length ?? 0 }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <Link to="/" className="flex items-center gap-2 px-2 py-1.5">
          <span className="grid size-7 place-items-center rounded-md bg-primary font-mono text-sm font-bold text-primary-foreground">
            FE
          </span>
          <span className="font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
            FantasyEdge
          </span>
        </Link>
        <TeamSwitcher />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Team advisor</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton asChild isActive={pathname.startsWith(item.to)} tooltip={item.label} disabled={!team}>
                    <Link to={item.to} onClick={closeOnPhone}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                  {!!badges[item.to] && (
                    <SidebarMenuBadge aria-label={`${badges[item.to]} trade offers waiting`}>{badges[item.to]}</SidebarMenuBadge>
                  )}
                </SidebarMenuItem>
              ))}
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname.startsWith('/connect')} tooltip="Connect">
                  <Link to="/connect" onClick={closeOnPhone}>
                    <Plug />
                    <span>{team ? 'Add a team' : 'Connect'}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname.startsWith('/settings')} tooltip="Settings">
                  <Link to="/settings" onClick={closeOnPhone}>
                    <Settings2 />
                    <span>Settings</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      {team && (
        <SidebarFooter className="group-data-[collapsible=icon]:hidden">
          <div className="flex flex-col gap-2 rounded-lg border bg-card/60 p-3 text-xs">
            <div className="flex flex-col">
              <span className="truncate font-medium text-sm">{team.teamName}</span>
              <span className="truncate text-muted-foreground">{team.leagueName}</span>
            </div>
            {league && (
              <span className="text-muted-foreground">
                Week {league.week} · {league.scoring} · {league.num_teams} teams
              </span>
            )}
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">Updated {fmtRelative(league?.last_synced_at)}</span>
              <Button
                size="sm"
                variant="outline"
                className="h-7"
                disabled={refresh.isPending}
                onClick={() => refresh.mutate({ body: { scope: 'league', league_id: team.leagueId } })}
              >
                <RefreshCw className={refresh.isPending ? 'animate-spin' : ''} />
                Update
              </Button>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground" data-testid="nfl-data-age">
                NFL data {nflBusy ? 'updating…' : fmtRelative(nflSyncedAt(status.data))}
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2"
                disabled={nflBusy}
                title="Scores, stats, injury reports and the player list (takes a minute)"
                onClick={() => nfl.mutate({ body: { scope: 'all' } })}
              >
                <CloudDownload className={nflBusy ? 'animate-pulse' : ''} />
                <span className="sr-only">Update NFL data</span>
              </Button>
            </div>
          </div>
        </SidebarFooter>
      )}
    </Sidebar>
  )
}
