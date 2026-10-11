export interface ViewerProfile {
  profile_id: string
  label: string
  mode: 'analyst' | 'casual' | 'player_focus'
  language: 'en' | 'es'
  favorite_team_id: ('home' | 'away') | null
  favorite_player_id: string | null
  focus_metric: string | null
  verbosity: 'short' | 'standard' | 'detailed'
}
