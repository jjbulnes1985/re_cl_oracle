export interface Property {
  score_id: number
  project_type: string | null
  county_name: string | null
  year: number | null
  real_value_uf: number | null
  surface_m2: number | null
  uf_m2_building: number | null
  opportunity_score: number | null
  undervaluation_score: number | null
  gap_pct: number | null
  data_confidence: number | null
  latitude: number | null
  longitude: number | null
  // V4 thesis features
  age?: number
  construction_year_bucket?: string
  city_zone?: string
  log_surface?: number
  // V4 OSM features
  dist_metro_km?: number
  dist_school_km?: number
  dist_park_km?: number
  amenities_500m?: number
  amenities_1km?: number
  // Calibrated prediction fields (commune-corrected)
  calibrated_gap_pct?: number | null
}

export interface PropertyDetail extends Property {
  predicted_uf_m2: number | null
  gap_percentile: number | null
  shap_top_features: ShapFeature[] | null
  // V4 additional OSM fields (detail only)
  dist_bus_stop_km?: number
  dist_hospital_km?: number
  dist_mall_km?: number
  age_sq?: number
  // Calibrated prediction fields (commune-corrected)
  calibrated_predicted_uf_m2?: number | null
  calibrated_gap_pct?: number | null
  commune_correction_uf_m2?: number | null
  commune_model_bias_pct?: number | null
}

export interface ShapFeature {
  feature: string
  shap: number
  direction: 'up' | 'down'
}

export interface CommuneStat {
  county_name: string
  n_transactions: number
  median_score: number | null
  pct_subvaloradas: number | null
  median_uf_m2: number | null
  median_gap_pct: number | null
}

export interface ScoreSummary {
  total_scored: number
  mean_score: number
  min_score: number
  max_score: number
  high_opp_count: number
  model_version: string
}

export interface ProfileInfo {
  name: string
  description: string
  weights: Record<string, number>
  is_default: boolean
}

export interface CustomWeights {
  undervaluation: number
  confidence: number
  location: number
  growth: number
  volume: number
}

export interface ScoreRequest {
  profile?: string
  weights?: CustomWeights
  county_name?: string
  project_type?: string
  limit?: number
}

export interface ScoredProperty {
  score_id: number
  county_name: string | null
  project_type: string | null
  opportunity_score: number | null
  undervaluation_score: number | null
  gap_pct: number | null
  uf_m2_building: number | null
  scoring_profile: string | null
}

export type ProfileName = 'default' | 'location' | 'growth' | 'liquidity' | 'custom'

export interface SavedSearch {
  id: number
  name: string
  filters: Record<string, unknown>
  created_at: string
}

export interface AuthUser {
  id: number
  email: string
}

export interface AuthToken {
  access_token: string
  token_type: string
}

export interface CommuneEnriched {
  county_name:        string
  n_transactions:     number
  median_score?:      number
  pct_subvaloradas?:  number
  median_uf_m2?:      number
  median_gap_pct?:    number
  crime_index?:       number
  crime_tier?:        string
  educacion_score?:   number
  hacinamiento_score?: number
  densidad_norm?:     number
}
