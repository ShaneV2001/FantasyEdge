import { Link } from '@tanstack/react-router'
import { AlertTriangle, Inbox, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { describeError } from '@/lib/errors'

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const p = describeError(error)
  return (
    <Alert variant="destructive" className="border-sell/40">
      <AlertTriangle />
      <AlertTitle>{p.message}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        <span>{p.hint}</span>
        {p.action && (
          <Button size="sm" variant="outline" asChild>
            <Link to={p.action.to} search={p.action.search}>
              {p.action.label}
            </Link>
          </Button>
        )}
        {onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RotateCw /> Retry
          </Button>
        )}
      </AlertDescription>
    </Alert>
  )
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <Card className="border-dashed bg-transparent">
      <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
        <div className="text-muted-foreground">{icon ?? <Inbox className="size-6" />}</div>
        <p className="font-medium">{title}</p>
        {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
      </CardContent>
    </Card>
  )
}

export function ListSkeleton({ rows = 5, height = 'h-20' }: { rows?: number; height?: string }) {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={`${height} w-full rounded-xl`} />
      ))}
    </div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
