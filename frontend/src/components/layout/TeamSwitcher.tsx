import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { Check, ChevronsUpDown, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import type { SavedTeamOut } from '@/api'
import { forgetTeamMutation, getSavedTeamsOptions, getSavedTeamsQueryKey, renameTeamMutation } from '@/api/@tanstack/react-query.gen'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'
import { describeError } from '@/lib/errors'
import { platformName } from '@/lib/format'
import { type ConnectedTeam, useTeamStore } from '@/stores/team'

export function toConnected(t: SavedTeamOut): ConnectedTeam {
  return {
    teamId: t.team_id,
    leagueId: t.league_id,
    teamName: t.team_name,
    leagueName: t.league_name,
    platform: t.platform as ConnectedTeam['platform'],
  }
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? '?').slice(0, 2)).toUpperCase()
}

const PLATFORM_LABEL: Record<string, string> = { sleeper: 'Sleeper', espn: 'ESPN', manual: 'Manual', demo: 'Demo' }

/** Sidebar team switcher: every saved team, plus add / rename / delete-or-forget. */
export function TeamSwitcher() {
  const team = useTeamStore((s) => s.team)
  const setTeam = useTeamStore((s) => s.setTeam)
  const clear = useTeamStore((s) => s.clear)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const saved = useQuery(getSavedTeamsOptions())
  const [dialog, setDialog] = useState<'rename' | 'forget' | null>(null)
  const [name, setName] = useState('')

  const teams = saved.data ?? []
  const active = teams.find((t) => t.team_id === team?.teamId)
  const manual = team?.platform === 'manual'
  const onError = (err: unknown) => toast.error(describeError(err).message, { description: describeError(err).hint })

  const switchTo = (t: SavedTeamOut) => {
    if (t.team_id === team?.teamId) return
    setTeam(toConnected(t))
    // the edit page only exists for manual teams; everything else works for any team
    if (pathname.startsWith('/team/edit') && t.platform !== 'manual') void navigate({ to: '/team' })
    else if (pathname === '/connect' || pathname === '/') void navigate({ to: '/advisor' })
    toast.success(`Switched to ${t.team_name}`, { description: t.league_name })
  }

  const rename = useMutation({
    ...renameTeamMutation(),
    onSuccess: () => {
      const n = name.trim()
      if (team) setTeam({ ...team, teamName: n, leagueName: n })
      void qc.invalidateQueries()
      setDialog(null)
      toast.success('Team renamed')
    },
    onError,
  })

  const forget = useMutation({
    ...forgetTeamMutation(),
    onSuccess: async (res) => {
      setDialog(null)
      const rest = teams.filter((t) => t.league_id !== res.league_id)
      if (rest.length > 0) {
        setTeam(toConnected(rest[0]))
        toast.success(manual ? 'Team deleted' : 'League forgotten', { description: `Switched to ${rest[0].team_name}` })
      } else {
        await navigate({ to: '/connect' })
        clear()
        toast.success(manual ? 'Team deleted' : 'League forgotten')
      }
      qc.removeQueries({ predicate: (q) => JSON.stringify(q.queryKey).includes(res.league_id) })
      void qc.invalidateQueries({ queryKey: getSavedTeamsQueryKey() })
    },
    onError,
  })

  if (!team) return null
  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton size="lg" tooltip={team.teamName} aria-label={`Team: ${team.teamName}. Switch team`}>
                <span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted font-mono text-xs font-semibold">
                  {initials(team.teamName)}
                </span>
                <span className="flex min-w-0 flex-1 flex-col text-left leading-tight">
                  <span className="truncate text-sm font-medium">{team.teamName}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {team.leagueName} · {PLATFORM_LABEL[team.platform] ?? team.platform}
                  </span>
                </span>
                <ChevronsUpDown className="ml-auto size-4 text-muted-foreground" />
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-72" align="start" side="bottom">
              <DropdownMenuLabel className="text-xs text-muted-foreground">Your teams</DropdownMenuLabel>
              {teams.map((t) => (
                <DropdownMenuItem key={t.team_id} onSelect={() => switchTo(t)} className="gap-2">
                  <span className="grid size-6 shrink-0 place-items-center rounded bg-muted font-mono text-[10px] font-semibold">
                    {initials(t.team_name)}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate">{t.team_name}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {t.league_name} · {PLATFORM_LABEL[t.platform] ?? t.platform} {t.season}
                    </span>
                  </span>
                  {t.team_id === team.teamId && <Check className="size-4" aria-label="Current team" />}
                </DropdownMenuItem>
              ))}
              {saved.isSuccess && teams.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-muted-foreground">No saved teams yet.</p>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => void navigate({ to: '/connect' })} className="gap-2">
                <Plus className="size-4" /> Add a team
              </DropdownMenuItem>
              {manual && (
                <DropdownMenuItem
                  onSelect={() => {
                    setName(team.teamName)
                    setDialog('rename')
                  }}
                  className="gap-2"
                >
                  <Pencil className="size-4" /> Rename team…
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => setDialog('forget')} className="gap-2 text-sell focus:text-sell">
                <Trash2 className="size-4" /> {manual ? 'Delete team…' : 'Forget this league…'}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>

      <Dialog open={dialog === 'rename'} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename team</DialogTitle>
            <DialogDescription>Only your manual team's name in FantasyEdge changes.</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              rename.mutate({ path: { team_id: team.teamId }, body: { name: name.trim() } })
            }}
            className="flex flex-col gap-4"
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="Team name" maxLength={80} autoFocus />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setDialog(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || rename.isPending}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={dialog === 'forget'} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{manual ? `Delete ${team.teamName}?` : `Forget ${team.leagueName}?`}</DialogTitle>
            <DialogDescription>
              {manual
                ? 'Your hand-entered roster and its settings are deleted from FantasyEdge.'
                : `FantasyEdge removes this league's rosters and everything it stored for it${active?.has_login ? ', including your saved ESPN login' : ''}. Nothing changes on ${team.platform === 'espn' || team.platform === 'sleeper' ? platformName(team.platform) : 'Sleeper or ESPN'}, and you can connect it again any time.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={forget.isPending}
              onClick={() => forget.mutate({ path: { team_id: team.teamId } })}
            >
              {manual ? 'Delete team' : 'Forget league'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
