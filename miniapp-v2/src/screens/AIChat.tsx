import { useState, useRef, useEffect } from 'preact/hooks';
import { ScreenHeader } from '@/components/layout/ScreenHeader';
import { Icon } from '@/components/ui/Icon';
import { api } from '@/lib/api';
import { endpoints } from '@/config';
import { haptic } from '@/lib/telegram';

interface Msg { role: 'user' | 'ai'; text: string; }

const SUGGESTIONS = [
  'Analyze the top trending TON memecoin',
  'Is there unusual whale activity today?',
  'Summarize TON market sentiment',
];

export default function AIChat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, busy]);

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    haptic.impact('light');
    setMessages((m) => [...m, { role: 'user', text: question }]);
    setInput('');
    setBusy(true);
    try {
      const res = await api.post<{ analysis?: string; answer?: string }>(endpoints.aiAnalysis, { question });
      setMessages((m) => [...m, { role: 'ai', text: res.analysis || res.answer || 'Analysis complete.' }]);
      haptic.notify('success');
    } catch {
      setMessages((m) => [...m, { role: 'ai', text: '⚠️ Could not reach the AI right now. Try again shortly.' }]);
      haptic.notify('error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div class="screen flex flex-col" style={{ minHeight: 'calc(100% - 1px)' }}>
      <ScreenHeader title="Ask AI" subtitle="On-chain analyst, on tap" />

      <div class="flex-1 space-y-3">
        {messages.length === 0 && (
          <div class="space-y-3 pt-2">
            <div class="text-center py-4 space-y-2">
              <span class="inline-grid place-items-center w-14 h-14 rounded-2xl bg-accent/12 text-accent">
                <Icon name="sparkles" size={26} />
              </span>
              <p class="text-hint text-sm">Your on-chain analyst. Try asking:</p>
            </div>
            {SUGGESTIONS.map((s, i) => (
              <button
                key={s}
                class="card-raised w-full text-left p-3.5 text-sm pressable flex items-center justify-between gap-2 animate-slide-up"
                style={{ animationDelay: `${i * 60}ms` }}
                onClick={() => send(s)}
              >
                <span>{s}</span>
                <Icon name="arrow-up" size={15} class="text-hint rotate-45 shrink-0" />
              </button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} class={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              class={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm animate-slide-up ${
                m.role === 'user' ? 'bg-accent text-accent-fg rounded-br-md' : 'card rounded-bl-md'
              }`}
            >
              {m.text}
            </div>
          </div>
        ))}

        {busy && (
          <div class="flex justify-start">
            <div class="card px-4 py-3 rounded-2xl rounded-bl-md">
              <span class="flex gap-1">
                <Dot /> <Dot delay="0.15s" /> <Dot delay="0.3s" />
              </span>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Composer */}
      <form
        class="sticky bottom-0 pt-3 flex items-center gap-2 bg-bg"
        style={{ paddingBottom: 'var(--tg-bottom)' }}
        onSubmit={(e) => { e.preventDefault(); send(input); }}
      >
        <input
          class="flex-1 bg-surface-2 rounded-2xl px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
          placeholder="Ask about any token, wallet, or trend…"
          value={input}
          onInput={(e) => setInput((e.target as HTMLInputElement).value)}
          aria-label="Your question"
        />
        <button type="submit" class="btn-primary px-4 py-3 aspect-square" disabled={busy || !input.trim()} aria-label="Send">
          <Icon name="send" size={18} />
        </button>
      </form>
    </div>
  );
}

function Dot({ delay = '0s' }: { delay?: string }) {
  return <span class="w-1.5 h-1.5 rounded-full bg-hint animate-bounce" style={{ animationDelay: delay }} />;
}
