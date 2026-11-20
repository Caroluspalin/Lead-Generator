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
  price?: string | null; // vain yrityksen nykyiseltä sivulta (backend tarkistaa)
}

export interface DemoContent {
  hero_title: string;
  hero_subtitle: string;
  about_title: string | null; // esittelyn otsikko (uudet pohjat); null = pohjan oletus
  about: string;
  services: DemoService[];
  price_note: string;
  service_area?: string | null; // vain remonttipohjat; tyhjä = osiota ei näytetä
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
  site_based: boolean; // tekstit nykyisen sivun tiedoista (sähköpostin maininta)
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
  static?: boolean; // remonttipohjat: ei AI-tekstiä, vain palvelulista ja toimialue muokattavissa
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
  // Tarjouksen ehdot vapaana tekstinä; tyhjä = ei ehto-osiota tarjoussivulla
  quote_terms: string | null;
  business_id: string | null;
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
  city: string | null; // kunta osoitteesta (naapurialueet), null = haettu kaupunki
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
  summary: SearchSummary | null;
}

// Hakulomakkeen sivun tila -suodattimet (backend SEARCH_STATUS_FILTERS)
export type SearchStatusFilter = 'no_website' | 'broken' | 'insecure' | 'not_mobile' | 'social_only';

export type SearchStopReason = 'target_reached' | 'call_limit' | 'area_exhausted';

export interface SearchSummary {
  requested: number;
  found: number;
  stop_reason: SearchStopReason;
  skipped_in_pipeline: number;
  skipped_dismissed: number;
  skipped_seen: number;
  filtered_out: number;
  searched_neighbors: boolean;
}

// GET /places/dismissed: vain place_id ja aika (Places-sisältöä ei tallenneta)
export interface DismissedPlace {
  place_id: string;
  maps_url: string;
  dismissed_at: string;
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

export type FollowUpSequenceStatus = 'draft' | 'active' | 'stopped' | 'replied' | 'completed';
export type FollowUpStepStatus = 'scheduled' | 'sending' | 'sent' | 'stopped' | 'replied' | 'failed' | 'needs_review';

export interface FollowUpStep {
  id: number;
  step_no: number;
  subject: string;
  body: string;
  status: FollowUpStepStatus;
  due_at: string | null;
  sent_at: string | null;
  last_error: string | null;
}

export interface FollowUpSequence {
  id: number;
  lead_id: number;
  status: FollowUpSequenceStatus;
  stop_reason: string | null;
  approved_at: string | null;
  replied_at: string | null;
  send_enabled: boolean;
  steps: FollowUpStep[];
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
  // Autodemo julkaisi demon: tarkista ennen yhteydenottoa
  review_before_contact: boolean;
  timma_fetched_at?: string | null;
  // Ostosignaalit: vain mitattu (PageSpeed, mobiili) tai sivulta luettu arvo
  pagespeed_lcp_s?: number | null;
  pagespeed_score?: number | null;
  pagespeed_at?: string | null;
  site_copyright_year?: number | null;
  // Julkaistu ja voimassa oleva demo. Vain GET /leads -vastauksessa (laskettu Demo-taulusta)
  demo_published?: boolean;
  // Julkaistun demon avaukset (vain GET /leads): ei botteja eikä omia esikatseluja
  demo_open_count?: number;
  demo_last_opened_at?: string | null;
  // Uusimman seurantasarjan tila ja seuraavan viestin aika (vain GET /leads)
  followup_status?: FollowUpSequenceStatus | null;
  followup_next_at?: string | null;
  followup_replied_at?: string | null;
  // Uusin tarjousversio ja sen avaukset (vain GET /leads)
  quote_id?: number | null;
  quote_version?: number | null;
  quote_status?: QuoteStatus | null;
  quote_net_cents?: number | null;
  quote_open_count?: number;
  quote_last_opened_at?: string | null;
  rating?: number | null;
  review_count?: number | null;
  business_status?: BusinessStatus | null;
  primary_type?: string | null;
  maps_url?: string | null;
  lead_score?: number | null;
  pipeline_status: PipelineStatus;
  source: string;
  notes?: string;
  deal_value?: number | null;
  recurring_monthly?: number | null;
  created_at: string;
  updated_at: string;
}


export type QuoteStatus = 'draft' | 'sent' | 'accepted' | 'superseded';

// Hinnat senteissä ilman alv:ia, alv-kanta sadasosaprosentteina (2550 = 25,5 %)
export interface ServiceCatalogItem {
  id: number;
  name: string;
  description: string | null;
  unit_price_cents: number;
  vat_rate_bp: number;
}

export interface QuoteLine {
  name: string;
  description: string | null;
  unit_price_cents: number;
  quantity: number;
  vat_rate_bp: number;
}

export interface Quote {
  id: number;
  lead_id: number;
  version: number;
  status: QuoteStatus;
  valid_days: number;
  valid_until: string | null;
  net_cents: number;
  vat_cents: number;
  gross_cents: number;
  sent_at: string | null;
  accepted_at: string | null;
  accepted_name: string | null;
  public_url: string | null;
  open_count: number;
  last_opened_at: string | null;
  lines: QuoteLine[];
}
