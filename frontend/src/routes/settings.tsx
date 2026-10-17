import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import type { SettingFieldOut, SettingsOut } from '@/api'
import {
  getUserSettingsOptions,
  resetUserSettingsMutation,
  updateUserSettingsMutation,
} from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { describeError } from '@/lib/errors'
import { FAAB_FORMULA } from '@/lib/faab'

const GROUP_NOTES: Record<string, string> = {
  Projections:
    'Defaults were picked by the walk-forward backtest (2022–25 seasons). Moving them away from the defaults can make projections less accurate.',
  'Buy/sell & targets': 'When a player gets a buy or sell call, and how the Buy targets page is cut.',
  Injuries: 'How much an injury designation discounts a player.',
  'Advisor & trades': 'How big an edge the advisor needs before it suggests a move.',
  'Waivers & FAAB': `How the Waivers page suggests FAAB bids. ${FAAB_FORMULA}`,
}

const fmt = (v: number) => String(Number(v.toFixed(3)))

function isValid(f: SettingFieldOut, v: number) {
  return !Number.isNaN(v) && v >= f.min && v <= f.max && (!f.integer || Number.isInteger(v))
}

function SettingRow({ field, value, onChange }: { field: SettingFieldOut; value: number; onChange: (v: number) => void }) {
  const id = `setting-${field.key}`
  const changed = value !== field.default
  const valid = isValid(field, value)
  return (
    <div className="grid gap-2 sm:grid-cols-[1fr_8rem] sm:items-start sm:gap-6">
      <div className="flex flex-col gap-1">
        <Label htmlFor={id}>{field.label}</Label>
        <p className="text-xs text-muted-foreground">{field.help}</p>
        <p className="text-xs text-muted-foreground">
          Default {fmt(field.default)} · allowed {fmt(field.min)}–{fmt(field.max)}
          {changed && (
            <>
              {' · '}
              <button
                type="button"
                className="underline underline-offset-2 hover:text-foreground"
                onClick={() => onChange(field.default)}
              >
                reset
              </button>
            </>
          )}
        </p>
      </div>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        min={field.min}
        max={field.max}
        step={field.integer ? 1 : 0.01}
        value={Number.isNaN(value) ? '' : value}
        aria-invalid={!valid}
        className={changed ? 'border-primary font-mono tabular-nums' : 'font-mono tabular-nums'}
        onChange={(e) => onChange(e.target.value === '' ? Number.NaN : Number(e.target.value))}
      />
    </div>
  )
}

function SettingsForm({ data }: { data: SettingsOut }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Record<string, number>>({})
  const done = (title: string) => () => {
    setDraft({})
    void qc.invalidateQueries()
    toast.success(title, { description: 'Every page now uses the new numbers.' })
  }
  const onError = (err: unknown) => toast.error(describeError(err).message, { description: describeError(err).hint })
  const save = useMutation({ ...updateUserSettingsMutation(), onSuccess: done('Settings saved'), onError })
  const reset = useMutation({ ...resetUserSettingsMutation(), onSuccess: done('Settings reset to defaults'), onError })

  const valueOf = (f: SettingFieldOut) => draft[f.key] ?? f.value
  const changes = Object.fromEntries(
    Object.entries(draft).filter(([k, v]) => v !== data.fields.find((f) => f.key === k)?.value),
  )
  const invalid = data.fields.some((f) => !isValid(f, valueOf(f)))
  const anyCustom = data.fields.some((f) => f.value !== f.default)
  const groups = [...new Set(data.fields.map((f) => f.group))]

  return (
    <div className="flex flex-col gap-6">
      {data.warning && (
        <Card className="border-destructive/50">
          <CardContent className="flex items-start gap-2 py-4 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
            {data.warning}
          </CardContent>
        </Card>
      )}
      {groups.map((g) => (
        <Card key={g}>
          <CardHeader>
            <CardTitle>{g}</CardTitle>
            {GROUP_NOTES[g] && <CardDescription>{GROUP_NOTES[g]}</CardDescription>}
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            {data.fields
              .filter((f) => f.group === g)
              .map((f) => (
                <SettingRow
                  key={f.key}
                  field={f}
                  value={valueOf(f)}
                  onChange={(v) => setDraft((d) => ({ ...d, [f.key]: v }))}
                />
              ))}
          </CardContent>
        </Card>
      ))}
      <div className="sticky bottom-0 flex flex-wrap items-center gap-3 border-t bg-background py-3">
        <Button
          disabled={invalid || Object.keys(changes).length === 0 || save.isPending}
          onClick={() => save.mutate({ body: changes })}
        >
          Save
        </Button>
        <Button variant="ghost" disabled={Object.keys(draft).length === 0} onClick={() => setDraft({})}>
          Discard changes
        </Button>
        <Button
          variant="outline"
          className="ml-auto"
          disabled={!anyCustom || reset.isPending}
          onClick={() => {
            if (window.confirm('Reset every setting to its default?')) reset.mutate({})
          }}
        >
          <RotateCcw /> Reset all
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">Saved in {data.path}. Only changed values are written.</p>
    </div>
  )
}

export function SettingsPage() {
  const q = useQuery(getUserSettingsOptions())
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Tune the model's weights and the thresholds behind buy/sell calls, injuries and advice. Changes apply to every page."
      />
      {q.isPending && <ListSkeleton rows={4} height="h-40" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && <SettingsForm data={q.data} />}
    </div>
  )
}
