import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { ScreenHeader } from '@/components/layout/ScreenHeader';
import { Icon } from '@/components/ui/Icon';
import { user, currentPlan, isPremium, ui, toast } from '@/store';
import { getReferralToken } from '@/lib/user';
import { tgUser, openTelegramLink, haptic } from '@/lib/telegram';
import { env } from '@/config';

export default function Settings() {
  const { route } = useLocation();
  const [refBusy, setRefBusy] = useState(false);

  const shareReferral = async () => {
    setRefBusy(true);
    haptic.impact('light');
    try {
      const token = await getReferralToken();
      const link = `https://t.me/${env.botUsername}?start=${token}`;
      const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(
        'Get AI-powered TON memecoin intelligence on TonGPT 🚀',
      )}`;
      openTelegramLink(shareUrl);
    } catch {
      toast('Could not generate referral link', 'error');
    } finally {
      setRefBusy(false);
    }
  };

  return (
    <div class="screen space-y-5">
      <ScreenHeader title="Profile" />

      {/* Identity */}
      <section class="card-raised p-5 flex items-center gap-4">
        {tgUser?.photo_url ? (
          <img src={tgUser.photo_url} alt="" class="w-14 h-14 rounded-full object-cover" />
        ) : (
          <div class="w-14 h-14 rounded-full bg-accent/20 grid place-items-center text-2xl">
            {(tgUser?.first_name ?? 'T')[0]}
          </div>
        )}
        <div>
          <p class="font-bold text-lg">{tgUser?.first_name ?? 'TonGPT user'}</p>
          {tgUser?.username && <p class="text-hint text-sm">@{tgUser.username}</p>}
        </div>
      </section>

      {/* Subscription */}
      <section class="card-raised p-5">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-hint text-xs uppercase tracking-wider">Subscription</p>
            <p class="text-xl font-bold flex items-center gap-2">
              {currentPlan.value}{isPremium.value && <span class="text-gold">👑</span>}
            </p>
            {user.status.value?.expiry && (
              <p class="text-hint text-xs">Renews {new Date(user.status.value.expiry).toLocaleDateString()}</p>
            )}
          </div>
          <button class="btn-primary px-4 py-2 text-sm" onClick={() => route('/pricing')}>
            {isPremium.value ? 'Change' : 'Upgrade'}
          </button>
        </div>
      </section>

      {/* Actions */}
      <section class="card-raised divide-hairline overflow-hidden">
        <RowButton icon="🎁" label="Invite & earn" hint="Share your referral link" onClick={shareReferral} busy={refBusy} />
        <RowButton icon="👛" label="Wallet" hint="Manage connection" onClick={() => route('/wallet')} />
        <RowButton icon="🎨" label="Theme" hint={ui.colorScheme.value === 'dark' ? 'Synced · Dark' : 'Synced · Light'} />
      </section>

      {/* Legal */}
      <section class="card-raised divide-hairline overflow-hidden">
        <RowButton icon="📜" label="Terms of Service" onClick={() => openTelegramLink(`https://t.me/${env.botUsername}?start=terms`)} />
        <RowButton icon="🔒" label="Privacy Policy" onClick={() => openTelegramLink(`https://t.me/${env.botUsername}?start=privacy`)} />
      </section>

      <p class="text-center text-hint text-xs">TonGPT · v2.0.0</p>
    </div>
  );
}

function RowButton({
  icon, label, hint, onClick, busy,
}: { icon: string; label: string; hint?: string; onClick?: () => void; busy?: boolean }) {
  return (
    <button class="w-full flex items-center gap-3 p-4 text-left active:bg-surface-2 transition-colors" onClick={onClick} disabled={busy}>
      <span class="text-xl">{icon}</span>
      <div class="flex-1">
        <p class="font-semibold text-sm">{label}</p>
        {hint && <p class="text-hint text-xs">{hint}</p>}
      </div>
      {busy ? <span class="text-hint">…</span> : <Icon name="chevron-right" size={16} class="text-hint" />}
    </button>
  );
}
