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

export type NavTab = 'search' | 'pipeline' | 'dashboard' | 'history' | 'settings';

// Demosivu (backend demo_site.py): AI kirjoittaa vain nämä tekstit, HTML tulee pohjasta
export interface DemoService {
  name: string;
  description: string;
}

export interface DemoContent {
  hero_title: string;
  hero_subtitle: string;
  about: string;
  services: DemoService[];
  price_note: string;
}

export interface DemoStoredContent extends DemoContent {
  opening_hours: string[];
}

export type DemoStatus = 'draft' | 'published' | 'expired';

export interface Demo {
  id: number;
  lead_id: number;
  template: string;
  color_scheme: string;
  content: DemoStoredContent;
  public_token: string;
  preview_url: string;
  status: DemoStatus;
  created_at: string;
  published_at: string | null;
  expires_at: string | null;
}

export interface DemoTemplateOption {
  id: string;
  label: string;
  color_schemes: { id: string; label: string }[];
}

// PUT /sender-profile -runko
export interface SenderProfileInput {
  name: string;
  company_name: string | null;
  phone: string | null;
  website: string | null;
  short_intro: string;
}

// GET /sender-profile
export interface SenderProfile extends SenderProfileInput {
  id: number;
  user_id: string;
  updated_at: string;
}

export type WebsiteStatus =
  | 'NO WEBSITE'
  | 'BROKEN WEBSITE'
  | 'INSECURE'
  | 'NOT MOBILE'
  | 'WEBSITE OK'
  | 'UNKNOWN';

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
  website_issue: string | null;
  discovery_method: string;
  rating: number | null;
  review_count: number | null;
  business_status: BusinessStatus | null;
  primary_type: string | null;
  maps_url: string | null;
  lead_score: number;
  already_saved: boolean;
}

export interface SearchUsage {
  api_calls: number;
  geocode_calls: number;
  text_search_calls: number;
  estimated_cost_usd: number;
}

// GET /search -vastaus
export interface SearchResponse {
  results: SearchResult[];
  usage: SearchUsage;
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
  website_issue?: string;
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
  website_issue?: string | null;
  email?: string | null;
  email_source?: string | null;
  do_not_contact: boolean;
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

