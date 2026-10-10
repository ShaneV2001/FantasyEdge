import { useQuery } from '@tanstack/react-query'
import { Outlet } from '@tanstack/react-router'

import { getStatusOptions } from '@/api/@tanstack/react-query.gen'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { AppSidebar } from './AppSidebar'

export function AppLayout() {
  const status = useQuery({ ...getStatusOptions(), staleTime: 5 * 60_000, retry: false })
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
              <Badge variant="outline" className="font-mono">
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
      ; NFL stats, play-by-play, schedules &amp; injuries from{' '}
      <a className="underline underline-offset-2" href="https://github.com/nflverse" target="_blank" rel="noreferrer">
        nflverse
      </a>{' '}
      (CC-BY 4.0; FTN data CC-BY-SA 4.0); market values from{' '}
      <a className="underline underline-offset-2" href="https://fantasycalc.com" target="_blank" rel="noreferrer">
        FantasyCalc
      </a>
      ; ID mapping from DynastyProcess. ff-edge is not affiliated with Sleeper, ESPN, Yahoo, FantasyCalc,
      nflverse or the NFL. Projections are estimates, not guarantees.
    </footer>
  )
}
