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
  about_title: string | null; // esittelyn otsikko (uudet pohjat); null = pohjan oletus
  about: string;
  services: DemoService[];
  price_note: string;
}

// Unsplash-kuva (hotlinkattava raw_url sisältää ixid-parametrin, joka pitää säilyttää)
export interface DemoPhoto {
  id: string;
  raw_url: string;
  alt: string;
  photographer_name: string;
  photographer_url: string;
  download_location: string;
  has_people: boolean;
}

export interface DemoImages {
  hero: DemoPhoto | null;
  mood: DemoPhoto[];
  options: DemoPhoto[];
}

// Aukiolojakso (Googlen day: 0 = sunnuntai), close "24:00" = keskiyö
export interface DemoOpeningPeriod {
  day: number;
  open: string;
  close: string;
}

export interface DemoStoredContent extends DemoContent {
  opening_hours: string[];
  opening_periods: DemoOpeningPeriod[];
  images: DemoImages;
}

export type DemoStatus = 'draft' | 'published' | 'expired';

export interface Demo {
  id: number;
  lead_id: number;
  template: string;
  color_scheme: string;
  content: DemoStoredContent;
  public_token: string;
  public_path: string; // julkinen polku: slug (taina-lantiainen-k7x2m) tai vanhoilla demoilla token
  preview_url: string; // backendin esikatselu (myös luonnokset)
  public_url: string | null; // julkaistu osoite (Worker / oma domain)
  publishing_enabled: boolean;
  status: DemoStatus;
  created_at: string;
  published_at: string | null;
  expires_at: string | null;
}

export interface DemoTemplateOption {
  id: string;
  label: string;
  version: number; // 2 = uudet pohjat (cafe ...), 1 = Classic
  color_schemes: { id: string; label: string }[];
}

// PUT /sender-profile -runko
export interface SenderProfileInput {
  name: string;
  company_name: string | null;
  brand_name: string | null; // allekirjoituksessa näkyvä nimi, esim. "Palin Web"
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

