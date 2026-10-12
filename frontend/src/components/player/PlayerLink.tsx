import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** A player's name that opens their player page. */
export function PlayerLink({ playerId, children, className }: { playerId: string; children: ReactNode; className?: string }) {
  return (
    <Link
      to="/players/$playerId"
      params={{ playerId }}
      className={cn('decoration-muted-foreground/60 underline-offset-2 hover:underline', className)}
    >
      {children}
    </Link>
  )
}
