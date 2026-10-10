import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import type { TeamOut } from '@/api'
import { getTeamOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { type BuilderInitial, ManualRosterBuilder, type Picked } from '@/components/team/ManualRosterBuilder'
import { Button } from '@/components/ui/button'
import { shapeFromRosterPositions } from '@/lib/lineup'
import { useTeamStore } from '@/stores/team'

export function toBuilderInitial(team: TeamOut): BuilderInitial {
  const picked: Picked[] = team.roster.map((p) => ({
    player_id: p.player_id,
    name: p.name,
    position: p.position,
    nfl_team: p.nfl_team,
    role: p.slot === 'starter' ? 'starter' : p.slot === 'ir' ? 'ir' : 'bench',
  }))
  return {
    teamId: team.team_id,
    name: team.team_name,
    numTeams: team.league.num_teams,
    scoring: team.league.scoring_preset ?? 'half_ppr',
    shape: shapeFromRosterPositions(team.league.roster_positions),
    picked,
  }
}

export function TeamEditPage() {
  const team = useTeamStore((s) => s.team)!
  const q = useQuery(getTeamOptions({ path: { team_id: team.teamId } }))

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader
        title="Edit team"
        description="Change players, who starts, bench and IR depth, scoring and league size. Projections and advice update as soon as you save."
      />
      {q.isPending && <ListSkeleton rows={4} height="h-24" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && q.data.league.platform !== 'manual' && (
        <EmptyState title="This team is synced from Sleeper">
          Make roster moves in Sleeper, then press <b>Update</b> in the sidebar to pull them in.
          <div className="mt-3">
            <Button asChild variant="outline" size="sm">
              <Link to="/team">Back to My Team</Link>
            </Button>
          </div>
        </EmptyState>
      )}
      {q.data && q.data.league.platform === 'manual' && (
        // key: remount with fresh state if the team changes underneath
        <ManualRosterBuilder key={q.data.team_id} initial={toBuilderInitial(q.data)} />
      )}
    </div>
  )
}
