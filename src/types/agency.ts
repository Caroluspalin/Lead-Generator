export type PipelineStatus =
  | 'Shortlisted'
  | 'Contacted'
  | 'Proposal Received'
  | 'Hired'
  | 'Rejected';

export const PIPELINE_STATUSES: PipelineStatus[] = [
  'Shortlisted',
  'Contacted',
  'Proposal Received',
  'Hired',
  'Rejected',
];

export type NavTab = 'search' | 'pipeline' | 'dashboard' | 'history';

export type WebsiteStatus = 'NO WEBSITE' | 'BROKEN WEBSITE' | 'NOT MOBILE' | 'WEBSITE OK';

// Places API (New) businessStatus; CLOSED_PERMANENTLY suodatetaan jo backendissä
export type BusinessStatus = 'OPERATIONAL' | 'CLOSED_TEMPORARILY' | 'CLOSED_PERMANENTLY';

// GET /search -vastauksen rivi (backendin GoogleSearchResult)
export interface SearchResult {
  name: string;
  place_id: string;
  address: string;
  phone: string | null;
  website: string | null;
  website_status: string;
  discovery_method: string;
  rating: number | null;
  review_count: number | null;
  business_status: BusinessStatus | null;
  primary_type: string | null;
  maps_url: string | null;
  lead_score: number;
  already_saved: boolean;
}

// Hakutulos UI:ssa (ei persistoida viela)
export interface Agency {
  id: string;
  name: string;
  city: string;
  address: string;
  phone?: string;
  website?: string;
  website_status: string;
  discovery_method?: string;
  rating?: number;
  review_count?: number;
  business_status?: BusinessStatus;
  primary_type?: string;
  maps_url?: string;
  lead_score?: number;
  already_saved?: boolean;
}

// Tallennettu liidi backendissa (vastaa Lead-taulua)
export interface SavedAgency {
  id: number;
  google_place_id?: string;
  name: string;
  city: string;
  address?: string;
  phone?: string;
  website?: string;
  website_status?: string;
  rating?: number | null;
  review_count?: number | null;
  business_status?: BusinessStatus | null;
  primary_type?: string | null;
  maps_url?: string | null;
  lead_score?: number | null;
  pipeline_status: PipelineStatus;
  source: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

