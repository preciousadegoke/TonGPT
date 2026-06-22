import { useEffect, useState } from 'preact/hooks';
import { ScreenHeader } from '@/components/layout/ScreenHeader';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/api';
import { endpoints } from '@/config';
import { timeAgo } from '@/lib/format';

type Tab = 'payments' | 'whales';

interface WhaleTx { wallet?: string; amount?: string; token?: string; time?: string; type?: string; }
interface Payment { plan?: string; amount?: string; method?: string; date?: string; }

export default function Activity() {
  const [tab, setTab] = useState<Tab>('whales');
  const [whales, setWhales] = useState<WhaleTx[] | null>(null);
  const [payments, setPayments] = useState<Payment[] | null>(null);

  useEffect(() => {
    api.get<WhaleTx[] | { transactions: WhaleTx[] }>(endpoints.whale)
      .then((d) => setWhales(Array.isArray(d) ? d : (d.transactions ?? [])))
      .catch(() => setWhales([]));
    api.get<Payment[] | { activity: Payment[] }>(endpoints.activity)
      .then((d) => setPayments(Array.isArray(d) ? d : (d.activity ?? [])))
      .catch(() => setPayments([]));
  }, []);

  return (
    <div class="screen space-y-4">
      <ScreenHeader title="Activity" subtitle="Whale moves & your payments" />

      <div class="grid grid-cols-2 gap-2 p-1 bg-surface-2 rounded-2xl" role="tablist">
        <TabBtn active={tab === 'whales'} onClick={() => setTab('whales')}>🐋 Whale alerts</TabBtn>
        <TabBtn active={tab === 'payments'} onClick={() => setTab('payments')}>🧾 Payments</TabBtn>
      </div>

      {tab === 'whales' ? (
        <List
          data={whales}
          empty="No whale activity captured yet."
          render={(t: WhaleTx, i) => (
            <div key={i} class="flex items-center justify-between p-4">
              <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-full bg-surface-2 grid place-items-center">🐋</div>
                <div>
                  <p class="text-sm font-semibold">{t.type ?? 'Transfer'} · {t.token ?? 'TON'}</p>
                  <p class="text-hint text-xs">{t.wallet ?? 'unknown wallet'}</p>
                </div>
              </div>
              <div class="text-right">
                <p class="text-sm font-semibold">{t.amount ?? '—'}</p>
                <p class="text-hint text-xs">{t.time ? timeAgo(t.time) : ''}</p>
              </div>
            </div>
          )}
        />
      ) : (
        <List
          data={payments}
          empty="No payments yet. Upgrade to unlock premium features."
          render={(p: Payment, i) => (
            <div key={i} class="flex items-center justify-between p-4">
              <div>
                <p class="text-sm font-semibold">{p.plan ?? 'Subscription'}</p>
                <p class="text-hint text-xs">{p.method ?? 'TON'} · {p.date ? new Date(p.date).toLocaleDateString() : ''}</p>
              </div>
              <p class="text-sm font-semibold text-positive">{p.amount ?? ''}</p>
            </div>
          )}
        />
      )}
    </div>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: any }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      class={`py-2.5 rounded-xl text-sm font-semibold transition-colors ${active ? 'bg-accent text-accent-fg' : 'text-hint'}`}
    >
      {children}
    </button>
  );
}

function List<T>({ data, empty, render }: { data: T[] | null; empty: string; render: (item: T, i: number) => any }) {
  if (data === null) {
    return (
      <div class="card divide-y divide-border">
        {[0, 1, 2, 3].map((i) => <div key={i} class="p-4"><Skeleton w="70%" /></div>)}
      </div>
    );
  }
  if (data.length === 0) {
    return <div class="card p-6 text-center text-hint text-sm">{empty}</div>;
  }
  return <div class="card divide-y divide-border">{data.map(render)}</div>;
}
