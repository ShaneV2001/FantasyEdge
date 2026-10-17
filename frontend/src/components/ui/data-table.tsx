import { rowSortingFeature, tableFeatures, type ReactTable, type RowData } from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import type { ReactNode } from 'react'

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

/** Per-column extras: classes shared by the header and the cells (alignment, hiding on phones). */
export interface DataColumnMeta {
  className?: string
  /** Shown in the header's tooltip/aria label when the title is abbreviated. */
  label?: string
}

/** Table features for server-sorted tables: sorting state lives outside (e.g. in the URL). */
export const sortableFeatures = tableFeatures({ rowSortingFeature, columnMeta: {} as DataColumnMeta })

/** shadcn-style data table over a TanStack Table v9 instance (rows already sorted and paged). */
export function DataTable<TData extends RowData>({
  table,
  rowClassName,
  empty,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  table: ReactTable<typeof sortableFeatures, TData, any>
  rowClassName?: (row: TData) => string | undefined
  empty?: ReactNode
}) {
  const rows = table.getRowModel().rows
  return (
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map((group) => (
          <TableRow key={group.id}>
            {group.headers.map((header) => {
              const meta = header.column.columnDef.meta
              const sorted = header.column.getIsSorted()
              const Icon = sorted === 'asc' ? ArrowUp : sorted === 'desc' ? ArrowDown : ArrowUpDown
              return (
                <TableHead
                  key={header.id}
                  className={meta?.className}
                  aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : undefined}
                >
                  {header.isPlaceholder ? null : header.column.getCanSort() ? (
                    <button
                      type="button"
                      onClick={header.column.getToggleSortingHandler()}
                      className={cn(
                        'inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                        sorted && 'text-foreground',
                      )}
                      aria-label={`Sort by ${meta?.label ?? header.column.id}`}
                    >
                      <table.FlexRender header={header} />
                      <Icon className={cn('size-3.5', !sorted && 'opacity-40')} />
                    </button>
                  ) : (
                    <table.FlexRender header={header} />
                  )}
                </TableHead>
              )
            })}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={table.getAllLeafColumns().length} className="py-10 text-center text-muted-foreground">
              {empty ?? 'Nothing to show.'}
            </TableCell>
          </TableRow>
        ) : (
          rows.map((row) => (
            <TableRow key={row.id} className={rowClassName?.(row.original)}>
              {row.getAllCells().map((cell) => (
                <TableCell key={cell.id} className={cell.column.columnDef.meta?.className}>
                  <table.FlexRender cell={cell} />
                </TableCell>
              ))}
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  )
}
