import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { PositionGradeOut } from '@/api'
import { TooltipProvider } from '@/components/ui/tooltip'

import { TeamGrades } from './TeamGrades'

const g = (position: string, grade: PositionGradeOut['grade']): PositionGradeOut => ({
  position, points: 10, league_avg: 9, rank: 2, teams: 10, grade, delta_pct: 0.1, z: 0.4,
})

describe('TeamGrades', () => {
  it('shows positions, kickers, defenses and flex slots in order', () => {
    const grades = Object.fromEntries(['SFLEX', 'DEF', 'QB', 'K', 'FLEX', 'RB', 'WR', 'TE'].map((p) => [p, g(p, 'B')]))
    render(
      <TooltipProvider>
        <TeamGrades grades={grades} />
      </TooltipProvider>,
    )
    const labels = screen.getAllByText(/^(QB|RB|WR|TE|K|DEF|FLEX|SFLEX)$/).map((el) => el.textContent)
    expect(labels).toEqual(['QB', 'RB', 'WR', 'TE', 'K', 'DEF', 'FLEX', 'SFLEX'])
  })
})
