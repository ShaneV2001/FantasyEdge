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

const STORAGE_KEY = 'fantasyedge:team'

// The app used to be called ff-edge: carry a team saved under the old key over, once.
try {
  const old = localStorage.getItem('ff-edge:team')
  if (old && !localStorage.getItem(STORAGE_KEY)) localStorage.setItem(STORAGE_KEY, old)
  localStorage.removeItem('ff-edge:team')
} catch {
  // storage unavailable (private mode): nothing to migrate
}

export const useTeamStore = create<TeamState>()(
  persist(
    (set) => ({
      team: null,
      setTeam: (team) => set({ team }),
      clear: () => set({ team: null }),
    }),
    { name: STORAGE_KEY, storage: createJSONStorage(() => localStorage), version: 1 },
  ),
)
