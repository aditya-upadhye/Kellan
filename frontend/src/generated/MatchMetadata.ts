export interface MatchMetadata {
  match_id: string
  competition: string
  venue: string
  home: Team
  away: Team
  scenario: string
  seed: number
}
export interface Team {
  team_id: 'home' | 'away'
  name: string
  short_name: string
  colors: TeamColors
  formation: string
  style: TeamStyle
  /**
   * @minItems 18
   * @maxItems 18
   */
  players: [
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player,
    Player
  ]
}
export interface TeamColors {
  primary: string
  secondary: string
}
export interface TeamStyle {
  possession: number
  press: number
  directness: number
}
export interface Player {
  player_id: string
  name: string
  number: number
  position: 'GK' | 'DF' | 'MF' | 'FW'
  role: 'GK' | 'CB' | 'FB' | 'DM' | 'CM' | 'AM' | 'W' | 'ST'
  traits: PlayerTraits
  starter: boolean
}
export interface PlayerTraits {
  pace: number
  passing: number
  finishing: number
  defending: number
}
