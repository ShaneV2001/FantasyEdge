import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'

import type { PositionGradeOut } from '@/api'
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { GRADE_ORDER } from '@/lib/format'

const config = {
  mine: { label: 'Your starters', color: 'var(--chart-1)' },
  league: { label: 'League average', color: 'var(--chart-2)' },
} satisfies ChartConfig

export function PositionStrengthChart({ grades }: { grades: Record<string, PositionGradeOut> }) {
  const data = GRADE_ORDER.filter((p) => grades[p])
    .map((p) => ({ position: p, mine: grades[p].points, league: grades[p].league_avg }))
  return (
    <ChartContainer config={config} className="aspect-auto h-56 w-full">
      <BarChart data={data} margin={{ left: -16, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="position" tickLine={false} axisLine={false} />
        <YAxis tickLine={false} axisLine={false} width={44} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Bar dataKey="mine" fill="var(--color-mine)" radius={4} />
        <Bar dataKey="league" fill="var(--color-league)" radius={4} />
      </BarChart>
    </ChartContainer>
  )
}
