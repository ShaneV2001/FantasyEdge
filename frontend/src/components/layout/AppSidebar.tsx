import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { ArrowLeftRight, CalendarRange, ClipboardPlus, Crosshair, LayoutList, ListOrdered, Plug, RefreshCw, Settings2, Sparkles, UserSearch, Users } from 'lucide-react'
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
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { describeError } from '@/lib/errors'
import { fmtRelative } from '@/lib/format'
import { useTeamStore } from '@/stores/team'

const NAV = [
  { to: '/advisor', label: 'Advisor', icon: Sparkles },
  { to: '/team', label: 'My Team', icon: Users },
  { to: '/startsit', label: 'Start/Sit', icon: LayoutList },
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
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Team advisor</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton asChild isActive={pathname.startsWith(item.to)} tooltip={item.label} disabled={!team}>
                    <Link to={item.to}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname.startsWith('/connect')} tooltip="Connect">
                  <Link to="/connect">
                    <Plug />
                    <span>{team ? 'Switch team' : 'Connect'}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname.startsWith('/settings')} tooltip="Settings">
                  <Link to="/settings">
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
          </div>
        </SidebarFooter>
      )}
    </Sidebar>
  )
}
