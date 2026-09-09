export type SupplyType = "conventional" | "managed" | "coworking" | "sale" | "other";
export type OfferingLevel = "yes" | "limited" | "no";
export type OccupancyStatus = "available" | "occupied" | "unknown";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface MicroMarket {
  id: string;
  code: string;
  name: string;
  city: string;
  sort_order: number;
}

export interface Organisation {
  id: string;
  name: string;
  slug: string;
  role: "developer" | "operator" | "both";
  offers_managed: OfferingLevel | null;
  offers_coworking: OfferingLevel | null;
  major_locations: string | null;
  is_active: boolean;
  website: string | null;
  notes: string | null;
}

export interface Space {
  id: string;
  building_id: string;
  option_label: string | null;
  floor_label: string | null;
  area_sqft: number | null;
  seats: number | null;
  condition: string | null;
  condition_detail: string | null;
  timeline: string | null;
  occupancy: OccupancyStatus;
  operator_id: string | null;
  operator_brand: string | null;
  rent_psf: number | null;
  cam_psf: number | null;
  price_per_seat: number | null;
  parking_charges: string | null;
  rental_escalation: string | null;
  deposit_months: number | null;
  lease_tenure_months: number | null;
  lock_in_months: number | null;
  notice_months: number | null;
  commercial_terms: string | null;
  is_derived: boolean;
  derivation_note: string | null;
  source_file: string | null;
  evidence: string | null;
  notes: string | null;
}

export interface BuildingImage {
  id: string;
  building_id: string;
  storage_path: string;
  caption: string | null;
  kind: string | null;
  sort_order: number;
  is_primary: boolean;
  bytes: number | null;
  source_file: string | null;
}

export interface Contact {
  id: string;
  building_id: string | null;
  organisation_id: string | null;
  name: string | null;
  designation: string | null;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
}

export interface Building {
  id: string;
  name: string;
  slug: string | null;
  address: string | null;
  locality: string | null;
  city: string;
  micro_market_id: string | null;
  developer_id: string | null;
  operator_id: string | null;
  operator_brand: string | null;
  supply_type: SupplyType;
  asset_type: string;
  structure: string | null;
  total_size_sqft: number | null;
  total_size_is_estimated: boolean;
  total_size_basis: string | null;
  avg_floor_plate_sqft: number | null;
  floor_plate_efficiency: string | null;
  power_kva: string | null;
  power_backup: string | null;
  car_parking_ratio: string | null;
  oc_available: boolean | null;
  building_details: string | null;
  latitude: number | null;
  longitude: number | null;
  source_file: string | null;
  report_period: string | null;
  disclosure_mode: string | null;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

/** A building joined with everything the UI shows alongside it. */
export interface BuildingWithRelations extends Building {
  micro_markets: Pick<MicroMarket, "code" | "name"> | null;
  developer: Pick<Organisation, "id" | "name"> | null;
  operator: Pick<Organisation, "id" | "name"> | null;
  spaces: Space[];
  building_images: BuildingImage[];
  contacts: Contact[];
}

export interface IngestJob {
  id: string;
  kind: string;
  status: JobStatus;
  label: string | null;
  total_files: number;
  done_files: number;
  buildings_upserted: number;
  spaces_upserted: number;
  images_uploaded: number;
  stats: Record<string, unknown>;
  error: string | null;
  log: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface Deck {
  id: string;
  title: string;
  client_name: string | null;
  prompt: string | null;
  criteria: Record<string, unknown>;
  building_ids: string[];
  template_name: string | null;
  storage_path: string | null;
  slide_count: number | null;
  status: JobStatus;
  created_at: string;
}

export interface DeckPreviewBuilding {
  id: string;
  name: string;
  micro_market: string | null;
  landlord: string | null;
  available_sqft: number | null;
  available_seats: number | null;
  rent_psf: number | null;
  supply_type: SupplyType;
}
