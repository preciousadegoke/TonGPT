# Telegram Mini-App test checklist

Test inside the **real Telegram client** (mobile + desktop) — the browser can't
exercise MainButton, Stars, or haptics. Use @BotFather → your bot → Mini-App URL
pointed at an HTTPS tunnel of `npm run dev`, or a deployed `dist/`.

## Boot & theme
- [ ] App opens, expands full-height, no scroll-to-close from vertical swipe
- [ ] No flash of wrong background colour on launch (anti-FOUC works)
- [ ] Switch Telegram theme Dark ↔ Light → app re-themes instantly, live
- [ ] Header colour matches app background
- [ ] Bottom content clears the home-indicator / safe area on iPhone

## Consent
- [ ] First-ever open shows the consent gate; Accept records v1 and proceeds
- [ ] Decline closes the Mini-App
- [ ] Re-open after accepting → goes straight to Home (no gate)

## Navigation & native controls
- [ ] Tab bar switches Home / Ask AI / Upgrade / Activity / Profile with haptic
- [ ] Selection haptic fires on tab change
- [ ] Wallet screen shows BackButton; tapping it returns to Home
- [ ] Lazy screens show a skeleton, then content (no white flash)

## Wallet (TonConnect + ton_proof)
- [ ] "Connect Wallet" opens the TonConnect modal with wallet list
- [ ] After connecting, address shows; status reads "Verified (ton_proof)"
- [ ] If proof fails, status shows amber "not verified" + reconnect hint
- [ ] Copy address works (success haptic + toast)
- [ ] Disconnect clears state everywhere (Home nudge reappears)
- [ ] Manifest loads over public HTTPS (check no console manifest error)

## Payments — TON
- [ ] Pricing cards render; "Most popular" highlighted; comparison table correct
- [ ] Tap a plan → checkout sheet; TON rail selected by default
- [ ] Without wallet → CTA says "Connect wallet to pay" and opens modal
- [ ] With wallet → CTA "Pay N TON" opens wallet to confirm
- [ ] Approve → optimistic "Activating…"/"Activated ✓", success toast, plan updates
- [ ] Reject in wallet → returns to idle, no error toast spam

## Payments — Stars
- [ ] Switch to Stars rail; price shows in ⭐
- [ ] Tap pay → native Telegram Stars invoice opens
- [ ] Complete → "paid" path: success toast, `/api/user/status` reflects new plan
- [ ] Cancel → returns to idle gracefully

## AI chat
- [ ] Suggestions render on empty state; tapping one sends it
- [ ] Typing indicator (3 dots) shows while awaiting response
- [ ] Response bubble animates in; auto-scrolls to newest
- [ ] Backend error → graceful "couldn't reach AI" message, error haptic

## Activity
- [ ] Whale alerts tab loads (skeleton → list or empty state)
- [ ] Payments tab loads; empty state if `/api/user/activity` absent (no crash)

## Profile / referral / deep links
- [ ] Subscription card shows current plan + expiry; Upgrade routes to Pricing
- [ ] "Invite & earn" opens Telegram share sheet with referral link
- [ ] `?startapp=pricing`-style deep link / start_param handled (referral token)
- [ ] Terms / Privacy open in Telegram

## Performance & resilience
- [ ] First load main chunk is small; tonconnect chunk loads only when wallet used
- [ ] Throttle network → skeletons everywhere, no layout shift
- [ ] Force a render error → ErrorBoundary shows "Something went wrong" + Reload
- [ ] Go offline → API NetworkFirst serves cache where available; toasts inform
- [ ] Lighthouse (mobile) performance ≥ 90 on the built app

## Accessibility
- [ ] All interactive elements reachable; visible focus ring on keyboard nav
- [ ] Tab bar exposes role=tab/aria-selected; sheet is role=dialog aria-modal
- [ ] Respects prefers-reduced-motion (animations collapse)
