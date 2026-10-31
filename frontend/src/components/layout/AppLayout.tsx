import { Outlet } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { useSyncTeamName } from '@/hooks/useSyncTeamName'
import { AppSidebar } from './AppSidebar'
import { StaleDataBanner, useStatus } from './DataFreshness'

export function AppLayout() {
  const status = useStatus()
  useSyncTeamName()
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-12 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 h-4" />
          <span className="text-sm text-muted-foreground">Fantasy football team advisor</span>
          <div className="ml-auto flex items-center gap-2">
            {status.data?.week && (
              <Badge
                variant="outline"
                className="font-mono"
                title={status.data.data_refreshing ? 'Updating NFL data…' : undefined}
              >
                {status.data.data_refreshing && <Loader2 className="animate-spin" />}
                {status.data.season} · Week {status.data.week}
              </Badge>
            )}
            {status.isError && (
              <Badge variant="destructive" title="Start the API with `python tasks.py api`">
                API offline
              </Badge>
            )}
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-4 md:p-6">
          <StaleDataBanner status={status.data} />
          <Outlet />
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}

function Footer() {
  return (
    <footer className="mx-auto w-full max-w-6xl px-4 pb-6 text-[11px] leading-relaxed text-muted-foreground md:px-6">
      <Separator className="mb-3" />
      Data: league &amp; trending data from the{' '}
      <a className="underline underline-offset-2" href="https://docs.sleeper.com" target="_blank" rel="noreferrer">
        Sleeper API
      </a>
      ; ESPN league data (read-only, your own login) from fantasy.espn.com; NFL stats, play-by-play, schedules &amp; injuries from{' '}
      <a className="underline underline-offset-2" href="https://github.com/nflverse" target="_blank" rel="noreferrer">
        nflverse
      </a>{' '}
      (CC-BY 4.0; FTN data CC-BY-SA 4.0); market values from{' '}
      <a className="underline underline-offset-2" href="https://fantasycalc.com" target="_blank" rel="noreferrer">
        FantasyCalc
      </a>
      ; ID mapping from DynastyProcess. FantasyEdge is not affiliated with Sleeper, ESPN, Yahoo, FantasyCalc,
      nflverse or the NFL. Projections are estimates, not guarantees.
    </footer>
  )
}
