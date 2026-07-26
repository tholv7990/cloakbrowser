export interface User {
  id: string;
  email: string;
  status: 'active' | 'suspended';
  role: string;
  created_at: string;
}

export interface UserDetail {
  user: User;
  plan: { id: string; name: string; max_devices: number } | null;
  devices: Device[];
}

export interface Device {
  id: string;
  name: string;
  platform: string;
  last_seen_at: string | null;
  revoked_at: string | null;
}

export interface ActivationKey {
  id: string;
  key_id?: string;
  key?: string;
  plan_id: string;
  status: 'active' | 'suspended' | 'revoked';
  uses_remaining: number;
  expires_at: string | null;
}

export interface Plan {
  id: string;
  name: string;
  max_devices: number;
  max_profiles: number;
  max_sessions: number;
}

export interface Release {
  channel: string;
  version: string;
  min_supported_version: string;
  published_at: string;
}

export interface AuditEvent {
  created_at: string;
  actor: string;
  action: string;
  subject_type: string;
  subject_id: string;
  data: Record<string, any>;
}

export interface Overview {
  users: number;
  users_suspended: number;
  keys: number;
  keys_active: number;
  redemptions: number;
  keys_expiring_30d: number;
}

export interface ListResponse<T> {
  items: T[];
  total: number;
}
