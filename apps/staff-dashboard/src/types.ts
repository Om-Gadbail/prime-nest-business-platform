/**
 * Backend API contracts (mirror of backend Pydantic schemas).
 * Single source of truth for the dashboard — components never
 * hand-shape API payloads.
 */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface UserSummary {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  is_active: boolean;
  is_verified: boolean;
  last_login_at: string | null;
}

export interface BusinessSummary {
  id: string;
  slug: string;
  name: string;
  business_type: string;
  status: string;
}

export interface MembershipSummary {
  business_id: string;
  role: string | null;
  status: string;
  is_default: boolean;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: UserSummary;
  business: BusinessSummary | null;
  membership: MembershipSummary | null;
  permissions: string[];
}

export interface MeResponse {
  user: UserSummary;
  business: BusinessSummary | null;
  membership: MembershipSummary | null;
  permissions: string[];
}

export interface AvailableBusiness {
  business: BusinessSummary;
  role: string | null;
  status: string;
  is_default: boolean;
}

export interface Lead {
  id: string;
  contact_id: string | null;
  customer_id: string | null;
  display_name: string;
  phone: string | null;
  email: string | null;
  source: string;
  source_detail: string;
  status: string;
  assigned_user_id: string | null;
  service_interest: string;
  message: string;
  follow_up_at: string | null;
  last_contacted_at: string | null;
  converted_at: string | null;
  lost_reason: string;
  consent_marketing: boolean;
  routed_by: string;
  routing_reason: string;
  routed_at: string | null;
  landing_page: string;
  referrer: string;
  utm_source: string;
  utm_medium: string;
  utm_campaign: string;
  utm_term: string;
  utm_content: string;
  created_at: string;
  updated_at: string;
}

export interface LeadActivity {
  id: string;
  lead_id: string;
  actor_user_id: string | null;
  activity_type: string;
  note: string;
  created_at: string;
}

export interface Booking {
  id: string;
  contact_id: string | null;
  customer_id: string | null;
  lead_id: string | null;
  booking_type: string;
  status: string;
  title: string;
  requested_start_at: string | null;
  requested_end_at: string | null;
  assigned_user_id: string | null;
  notes: string;
  source: string;
  cancellation_reason: string;
  created_at: string;
  updated_at: string;
}

export interface Contact {
  id: string;
  first_name: string;
  last_name: string;
  display_name: string;
  phone: string | null;
  email: string | null;
  preferred_contact_channel: string;
  source: string;
  notes: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Customer {
  id: string;
  contact_id: string;
  status: string;
  customer_since: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
  contact: Contact | null;
}

export interface StaffTask {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  assigned_to_user_id: string | null;
  created_by_user_id: string | null;
  due_at: string | null;
  completed_at: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface StaffNotification {
  id: string;
  notification_type: string;
  title: string;
  body: string;
  severity: string;
  read_at: string | null;
  source_type: string | null;
  source_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
  expires_at: string | null;
}

export interface AuditEvent {
  id: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  actor_user_id: string | null;
  result: string;
  request_id: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface DashboardOverview {
  business_id: string;
  generated_at: string;
  leads: { new: number; follow_ups_due: number; created_today: number };
  bookings: { requested: number; created_today: number };
  notifications: { unread: number };
  tasks: { mine_open: number; mine_overdue: number; open_total: number };
  recent_leads: Array<{
    id: string;
    display_name: string;
    status: string;
    source: string;
    created_at: string;
  }>;
  recent_activity: Array<{
    id: string;
    lead_id: string;
    activity_type: string;
    note: string;
    actor_user_id: string | null;
    created_at: string;
  }>;
}

export interface StatusSummary {
  by_status: Record<string, number>;
  total: number;
}

export interface PersonLink {
  link_id: string;
  contact_id: string;
  link_type: string;
  confidence: string;
  created_at: string;
}

export interface PersonView {
  person_id: string;
  phone_masked: string;
  email_masked: string;
  links: PersonLink[];
}

export interface BusinessSettings {
  branding: Record<string, unknown>;
  contact: Record<string, unknown>;
  address: Record<string, unknown>;
  hours: Record<string, unknown>;
  localization: Record<string, unknown>;
  operational: Record<string, unknown>;
}

/* Blocks 5-7 operational contracts (mirror of backend schemas/operations.py). */

export interface Member {
  id: string;
  customer_id: string | null;
  contact_id: string | null;
  lead_id: string | null;
  display_name: string;
  phone: string | null;
  email: string | null;
  status: string;
  source: string;
  emergency_contact_name: string;
  emergency_contact_phone: string | null;
  seat_preference: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface MembershipPlan {
  id: string;
  code: string;
  name: string;
  category: string;
  duration_months: number;
  price: string;
  currency: string;
  is_best_value: boolean;
  is_active: boolean;
  features: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Membership {
  id: string;
  member_id: string;
  plan_id: string | null;
  customer_id: string | null;
  status: string;
  payment_state: string;
  start_date: string;
  end_date: string;
  price: string;
  discount: string;
  final_amount: string;
  currency: string;
  plan_name_snapshot: string;
  plan_version_snapshot: number;
  notes: string;
  cancel_reason: string;
  cancelled_at: string | null;
  renewed_from_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Payment {
  id: string;
  member_id: string | null;
  membership_id: string | null;
  customer_id: string | null;
  amount: string;
  currency: string;
  method: string;
  provider: string;
  status: string;
  paid_at: string | null;
  due_at: string | null;
  invoice_no: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface Attendance {
  id: string;
  member_id: string;
  membership_id: string | null;
  seat_id: string | null;
  attendance_date: string;
  checked_in_at: string;
  checked_out_at: string | null;
  source: string;
  notes: string;
  created_at: string;
}

export interface Renewal {
  id: string;
  member_id: string;
  membership_id: string;
  new_membership_id: string | null;
  previous_plan_id: string | null;
  new_plan_id: string | null;
  renewal_amount: string;
  currency: string;
  status: string;
  due_date: string;
  renewed_at: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface SeatArea {
  id: string;
  code: string;
  name: string;
  floor: string;
  description: string;
  created_at: string;
}

export interface Seat {
  id: string;
  area_id: string | null;
  seat_number: string;
  seat_type: string;
  status: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface SeatAllocation {
  id: string;
  seat_id: string;
  member_id: string;
  membership_id: string | null;
  status: string;
  allocated_at: string;
  released_at: string | null;
  notes: string;
  created_at: string;
}

export interface SeatAvailability {
  total: number;
  available: number;
  allocated_active: number;
  by_status: Record<string, number>;
}

export interface Approval {
  id: string;
  entity_type: string;
  entity_id: string | null;
  action: string;
  status: string;
  title: string;
  reason: string;
  decision_note: string;
  requested_by_user_id: string | null;
  decided_by_user_id: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

/* Owner command-center contracts (mirror of backend schemas/owner.py). */

export interface OwnerBusinessRef {
  id: string;
  slug: string;
  name: string;
  business_type: string;
}

export interface MembershipStats {
  active_memberships: number;
  active_members: number;
  new_members_today: number;
  expiring_soon: number;
  expired: number;
  by_status: Record<string, number>;
  total: number;
}

export interface RevenueStats {
  collected: string;
  pending: string;
  overdue: string;
  refunded: string;
  payment_count: number;
  average_transaction: string;
  by_status: Record<string, { count: number; amount: string }>;
  by_method: Record<string, { count: number; amount: string }>;
}

export interface LeadFunnel {
  total: number;
  by_status: Record<string, number>;
  by_source: Record<string, number>;
  converted: number;
  eligible: number;
  lead_conversion_rate: number;
  booked: number;
  booking_conversion_rate: number;
}

export interface OwnerBusinessOverview {
  business: OwnerBusinessRef;
  generated_at: string;
  membership: MembershipStats;
  revenue: RevenueStats;
  leads: LeadFunnel;
  bookings: { by_status: Record<string, number>; total: number };
  attendance_today: { total: number; currently_checked_in: number | null; by_source: Record<string, number> };
  renewals: { by_status: Record<string, number>; total: number; due_soon: number; overdue: number; pending_amount: string };
  seats?: { total: number; available: number; allocated_active: number; by_status: Record<string, number> } | null;
}

export interface OwnerRevenueReport {
  business_id: string;
  generated_at: string;
  window: { start: string | null; end: string | null };
  summary: RevenueStats;
  daily_trend: Array<{ date: string; count: number; amount: string }>;
}

export interface OwnerLeadsReport {
  business_id: string;
  generated_at: string;
  formulas: Record<string, string>;
  funnel: LeadFunnel;
  daily_trend: Array<{ date: string; count: number }>;
}

export interface CombinedBusinessItem {
  business: OwnerBusinessRef;
  revenue: RevenueStats;
  leads: LeadFunnel;
  membership: MembershipStats;
  attendance_today: { total: number; currently_checked_in: number | null; by_source: Record<string, number> };
  renewals: { by_status: Record<string, number>; total: number; due_soon: number; overdue: number; pending_amount: string };
  seats?: { total: number; available: number; allocated_active: number; by_status: Record<string, number> } | null;
}

export interface CombinedOverview {
  generated_at: string;
  scope: string;
  totals: Record<string, unknown>;
  businesses: CombinedBusinessItem[];
}

// Blocks 8-12: automation / communications / AI / growth / analytics.
export interface AutomationRule {
  id: string;
  business_id: string;
  name: string;
  event_type: string;
  is_active: boolean;
  priority: number;
  conditions: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  config: Record<string, unknown>;
}

export interface AutomationExecution {
  id: string;
  business_id: string;
  rule_id: string | null;
  event_type: string;
  status: string;
  attempt_count: number;
  idempotency_key: string;
  correlation_id: string;
  error: string;
}

export interface Conversation {
  id: string;
  channel: string;
  external_id: string;
  status: string;
  subject_name: string;
}

export interface Message {
  id: string;
  conversation_id: string | null;
  direction: string;
  channel: string;
  body: string;
  status: string;
  provider: string;
}

export interface MessageTemplate {
  id: string;
  code: string;
  channel: string;
  name: string;
  body: string;
  is_active: boolean;
}

export interface AIRecommendation {
  id: string;
  rec_type: string;
  title: string;
  reason: string;
  confidence: string;
  suggested_action: string;
  status: string;
  risk_level: string;
}

export interface GrowthSource {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface AnalyticsMetrics {
  period_days: number;
  leads: number;
  leads_prev: number;
  bookings: number;
  customers: number;
  converted_leads: number;
  conversion_rate: number;
  revenue: string;
  revenue_prev: string;
  payments: number;
  memberships_active: number;
  renewals_pending: number;
  attendance: number;
  members_total: number;
  seats_total: number;
  seats_occupied: number;
  occupancy_rate: number;
  funnel_by_source: Record<string, { leads: number; converted: number }>;
  source: string;
}

export interface IntelligenceFinding {
  metric: string;
  trend: string;
  driver: string;
  exception: string | null;
  possible_action: string;
  values: Record<string, unknown>;
}

export interface DailyBrief {
  id: string;
  report_date: string;
  yesterday: Record<string, unknown>;
  today: Record<string, unknown>;
  trend: Record<string, unknown>;
  exceptions: Array<Record<string, unknown>>;
  recommended_actions: string[];
}
