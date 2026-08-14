export type Role = "owner" | "manager" | "agent" | "cold_caller";

export type User = {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  role: Role;
  is_available: boolean | null;
  created_at?: string;
  deleted_at?: string | null;
};

export type Assignee = {
  user_id: number;
  name: string;
  role: Role;
  assigned_by_name: string | null;
  created_at: string;
  note: string | null;
};

export type Contact = {
  id: number;
  first_name: string;
  last_name: string | null;
  email: string | null;
  phone: string | null;
  contact_details_masked: boolean;
  /** False for an imported number nobody has flagged as a lead yet. */
  is_lead: boolean;
  batch_id: number | null;
  /** Staff working this lead in addition to its owner. Usually empty. */
  assignees: Assignee[];
  lead_source: string | null;
  campaign: string | null;
  budget_min: string | null;
  budget_max: string | null;
  preferred_locations: string[] | null;
  property_type_interest: string | null;
  buyer_type: string | null;
  lead_score: number | null;
  stage: string | null;
  owner_id: number | null;
  owner_name: string | null;
  created_at: string;
  updated_at: string;
  last_activity_at: string | null;
};

export type Property = {
  id: number;
  title: string | null;
  location: string;
  building: string | null;
  property_type: string | null;
  listing_type: "rent" | "outright";
  price: string | null;
  status: string | null;
  source: string | null;
  posted_by_agent_id: number | null;
  posted_by_name: string | null;
  created_at: string;
  showing_count: number | null;

  // Phase 3: populated on WhatsApp-sourced listings, null on manual ones.
  bhk: number | null;
  area_sqft: number | null;
  furnishing: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  source_group: string | null;
  raw_message: string | null;
  extraction_confidence: number | null;
  review_state: string | null;
  last_seen_at: string | null;
  /** Times this listing has been seen across all monitored groups. */
  sighting_count: number | null;
};

export type PropertyMatch = {
  property: Property;
  score: number;
  /** Why this was suggested. Shown verbatim — an opaque score isn't trusted. */
  reasons: string[];
};

export type PropertySource = {
  id: number;
  property_id: number;
  message_id: number | null;
  group_name: string | null;
  posted_by_name: string | null;
  posted_by_phone: string | null;
  raw_message: string | null;
  relation: "origin" | "duplicate" | string;
  match_score: number | null;
  seen_at: string;
};

export type UserWorkload = {
  user: User;
  active_leads: number;
  open_tasks: number;
  overdue_tasks: number;
  calls_last_7d: number;
  showings_last_7d: number;
  last_active_at: string | null;
};

export type WhatsAppGroup = {
  id: number;
  group_jid: string;
  name: string;
  note: string | null;
  is_active: boolean;
  created_at: string;
  last_message_at: string | null;
  message_count: number;
  listing_count: number;
  pending_count: number | null;
};

export type WhatsAppMessage = {
  id: number;
  group_id: number;
  group_name: string | null;
  sender_name: string | null;
  body: string;
  sent_at: string | null;
  received_at: string;
  status: string;
  attempts: number;
  error: string | null;
  listings_found: number;
  listings_new: number;
  processed_at: string | null;
};

export type IngestionStatus = {
  groups_active: number;
  groups_total: number;
  pending: number;
  processing: number;
  failed_last_24h: number;
  messages_last_24h: number;
  listings_last_24h: number;
  properties_from_whatsapp: number;
  duplicates_merged: number;
  needs_review: number;
  last_message_at: string | null;
  last_processed_at: string | null;
  extraction_configured: boolean;
};

export const INGEST_STATUS_LABELS: Record<string, string> = {
  pending: "Queued",
  processing: "Extracting",
  extracted: "Listing found",
  duplicate: "Repost — merged",
  not_listing: "Not inventory",
  failed: "Failed",
};

export type Showing = {
  contact_id: number;
  contact_name: string | null;
  property_id: number;
  property_title: string | null;
  property_location: string | null;
  shown_by_agent_id: number | null;
  shown_by_name: string | null;
  interest_level: string | null;
  shown_at: string;
};

export type CallLog = {
  id: number;
  contact_id: number | null;
  contact_name: string | null;
  caller_id: number;
  caller_name: string | null;
  outcome: string;
  temperature: string | null;
  notes: string | null;
  flagged_for_owner: boolean | null;
  follow_up_at: string | null;
  created_at: string;
};

export type Activity = {
  id: number;
  contact_id: number | null;
  contact_name: string | null;
  property_id: number | null;
  property_title: string | null;
  user_id: number | null;
  user_name: string | null;
  type: string;
  body: string | null;
  occurred_at: string;
};

export type FeedItem = {
  kind: "call" | "activity" | "showing";
  occurred_at: string;
  user_id: number | null;
  user_name: string | null;
  contact_id: number | null;
  contact_name: string | null;
  property_id: number | null;
  property_title: string | null;
  title: string;
  detail: string | null;
  tone: "neutral" | "positive" | "warning" | "signal";
  outcome: string | null;
  temperature: string | null;
  flagged: boolean;
};

/** The only client data a call queue carries — see schemas.QueueContact. */
export type QueueContact = {
  id: number;
  first_name: string;
  last_name: string | null;
  phone: string | null;
};

export type StaffPerformance = {
  user: User;
  calls: number;
  calls_by_outcome: Record<string, number>;
  connected: number;
  /** Fraction, or null when they have made no calls — which is not 0%. */
  connect_rate: number | null;
  showings: number;
  escalations: number;
  leads_assigned: number;
  leads_by_stage: Record<string, number>;
  closed: number;
  conversion_rate: number | null;
  tasks_open: number;
  tasks_overdue: number;
  /** Median hours from lead created to their first call on it. */
  median_response_hours: number | null;
  last_active_at: string | null;
};

export type TeamPerformance = {
  days: number;
  since: string;
  staff: StaffPerformance[];
  total_calls: number;
  total_showings: number;
  total_closed: number;
};

export type QueueItem = {
  contact: QueueContact;
  /** Why this lead surfaced now. Operational, not client data. */
  reason: string;
  priority: number;
  due_at: string | null;
};

export type Task = {
  id: number;
  contact_id: number | null;
  contact_name: string | null;
  assigned_to: number;
  assigned_to_name: string | null;
  title: string;
  due_at: string | null;
  status: string;
  source_call_log_id: number | null;
  created_at: string;
  completed_at: string | null;
};

export type AuditEntry = {
  id: number;
  user_id: number;
  user_name: string | null;
  action: string;
  resource_type: string;
  resource_id: number | null;
  detail: Record<string, unknown> | null;
  occurred_at: string;
};

export type Paged<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type ApiError = {
  error: { code: string; message: string };
  candidates?: DuplicateCandidate[];
};

export type DuplicateCandidate = {
  id: number;
  name: string;
  phone_last4: string | null;
  match: "phone_exact" | "name_fuzzy";
  score: number;
  owner_name: string | null;
  stage: string | null;
};

export const CALL_OUTCOMES = [
  // Ordered by how often a cold caller actually picks them, not alphabetically
  // — DESIGN_RULES.md asks the common cases to surface first.
  { value: "connected", label: "Connected" },
  { value: "not_reachable", label: "Not Reachable" },
  { value: "interested", label: "Interested" },
  { value: "callback_requested", label: "Callback Requested" },
  { value: "not_interested", label: "Not Interested" },
  { value: "wrong_number", label: "Wrong Number" },
] as const;

export const TEMPERATURES = [
  { value: "hot", label: "Hot" },
  { value: "warm", label: "Warm" },
  { value: "cold", label: "Cold" },
] as const;

export const STAGES = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "site_visit_scheduled", label: "Visit Scheduled" },
  { value: "visited", label: "Visited" },
  { value: "negotiating", label: "Negotiating" },
  { value: "closed", label: "Closed" },
  { value: "lost", label: "Lost" },
] as const;

export const INTEREST_LEVELS = [
  { value: "inquired", label: "Inquired" },
  { value: "site_visit_scheduled", label: "Visit Scheduled" },
  { value: "site_visit_done", label: "Visit Done" },
  { value: "negotiating", label: "Negotiating" },
] as const;

export type ImportRowPreview = {
  row_number: number;
  name: string;
  phone: string;
  email: string | null;
  location: string | null;
  status: "new" | "duplicate" | "invalid";
  detail: string | null;
};

export type ImportPreview = {
  filename: string;
  sheet_name: string | null;
  header_row: number | null;
  /** field -> the spreadsheet column it was read from. */
  detected_columns: Record<string, string>;
  total_rows: number;
  importable: number;
  duplicates: number;
  invalid: number;
  warnings: string[];
  sample: ImportRowPreview[];
};

export type ImportAssignment = {
  user_id: number;
  name: string;
  assigned: number;
};

export type ImportResult = {
  batch_id: number;
  batch_name: string;
  imported: number;
  duplicates: number;
  invalid: number;
  assignments: ImportAssignment[];
};

/**
 * One uploaded calling list, with how it is actually doing.
 *
 * Rates are `null` rather than 0 when their denominator is empty — a list
 * uploaded this morning and a list that was worked hard and produced nothing
 * both read "0%" otherwise, and they call for opposite decisions.
 */
export type BatchPerformance = {
  id: number;
  name: string;
  source_filename: string | null;
  uploaded_by: string | null;
  created_at: string;
  archived_at: string | null;

  /** The file as delivered, before dedup — how clean the source was. */
  total_rows: number;
  duplicate_rows: number;
  invalid_rows: number;

  size: number;
  called: number;
  uncalled: number;
  reached: number;
  leads: number;
  showings: number;
  closed: number;

  contact_rate: number | null;
  reach_rate: number | null;
  conversion_rate: number | null;

  assigned_to: string[];
  last_activity_at: string | null;
};
