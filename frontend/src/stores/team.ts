import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export interface ConnectedTeam {
  teamId: string
  leagueId: string
  teamName: string
  leagueName: string
  platform: 'sleeper' | 'manual'
  username?: string
}

interface TeamState {
  team: ConnectedTeam | null
  setTeam: (team: ConnectedTeam) => void
  clear: () => void
}

export const useTeamStore = create<TeamState>()(
  persist(
    (set) => ({
      team: null,
      setTeam: (team) => set({ team }),
      clear: () => set({ team: null }),
    }),
    { name: 'ff-edge:team', storage: createJSONStorage(() => localStorage), version: 1 },
  ),
)
