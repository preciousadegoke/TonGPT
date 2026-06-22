/** User/subscription + consent helpers backed by the FastAPI endpoints. */
import { api } from '@/lib/api';
import { endpoints } from '@/config';
import { user, type UserStatus } from '@/store';

export async function refreshUserStatus() {
  try {
    user.status.value = await api.get<UserStatus>(endpoints.userStatus);
  } catch {
    user.status.value = { plan: 'Free', expiry: null, is_premium: false };
  } finally {
    user.loading.value = false;
  }
}

export async function checkConsent(): Promise<boolean> {
  try {
    const { accepted } = await api.get<{ accepted: boolean }>(endpoints.consentStatus);
    user.consentAccepted.value = accepted;
    return accepted;
  } catch {
    user.consentAccepted.value = false;
    return false;
  }
}

export async function recordConsent() {
  await api.post(endpoints.recordConsent, { version: 'v1' });
  user.consentAccepted.value = true;
}

export async function getReferralToken(): Promise<string> {
  const { token } = await api.get<{ token: string }>(endpoints.referralToken);
  return token;
}
