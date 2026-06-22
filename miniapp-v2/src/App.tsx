import { LocationProvider, Router, Route, lazy, ErrorBoundary as IsoErrorBoundary } from 'preact-iso';
import { useEffect } from 'preact/hooks';
import { bootstrapTelegram } from '@/lib/telegram';
import { initWalletListener } from '@/lib/tonconnect';
import { useTheme } from '@/hooks/useTheme';
import { checkConsent, refreshUserStatus } from '@/lib/user';
import { user } from '@/store';

import { TabBar } from '@/components/layout/TabBar';
import { ToastHost } from '@/components/ui/Toast';
import { AppErrorBoundary } from '@/components/ui/ErrorBoundary';
import { ScreenFallback } from '@/components/ui/ScreenFallback';
import { ConsentGate } from '@/components/ConsentGate';
import { BootSplash } from '@/components/BootSplash';

// Code-split every screen — only the active route's JS is fetched.
const Home = lazy(() => import('@/screens/Home'));
const Pricing = lazy(() => import('@/screens/Pricing'));
const Wallet = lazy(() => import('@/screens/Wallet'));
const AIChat = lazy(() => import('@/screens/AIChat'));
const Activity = lazy(() => import('@/screens/Activity'));
const Settings = lazy(() => import('@/screens/Settings'));

export function App() {
  useTheme();

  useEffect(() => {
    bootstrapTelegram();
    initWalletListener();
    // Kick off the two independent boot fetches in parallel.
    void checkConsent();
    void refreshUserStatus();
  }, []);

  if (user.loading.value && user.consentAccepted.value === null) {
    return <BootSplash />;
  }

  if (user.consentAccepted.value === false) {
    return <ConsentGate />;
  }

  return (
    <LocationProvider>
      <AppErrorBoundary>
        <div class="flex flex-col h-full">
          <main class="flex-1 overflow-y-auto overflow-x-hidden" role="main">
            <IsoErrorBoundary>
              <Router>
                <Route path="/" component={withFallback(Home)} />
                <Route path="/pricing" component={withFallback(Pricing)} />
                <Route path="/wallet" component={withFallback(Wallet)} />
                <Route path="/ai" component={withFallback(AIChat)} />
                <Route path="/activity" component={withFallback(Activity)} />
                <Route path="/settings" component={withFallback(Settings)} />
                <Route default component={withFallback(Home)} />
              </Router>
            </IsoErrorBoundary>
          </main>
          <TabBar />
          <ToastHost />
        </div>
      </AppErrorBoundary>
    </LocationProvider>
  );
}

// Each lazy screen shows its skeleton while its chunk loads.
function withFallback(Comp: any) {
  return (props: any) => (
    <Comp {...props} fallback={<ScreenFallback />} />
  );
}
