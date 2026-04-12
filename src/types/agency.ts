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

export type WebsiteStatus = 'NO WEBSITE' | 'BROKEN WEBSITE' | 'NOT MOBILE' | 'WEBSITE OK';

// Hakutulos backendista (ei persistoida viela)
export interface Agency {
  id: string;
  name: string;
  city: string;
  address: string;
  phone?: string;
  website?: string;
  website_status: string;
  discovery_method?: string;
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
  pipeline_status: PipelineStatus;
  source: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

