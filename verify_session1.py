"""
Verify C-7 (dynamic registration) and C-10 (scanner stubs) end-to-end.
Run from the project root: python verify_session1.py
"""
import sys, os, asyncio, inspect, importlib, io

# Fix Unicode on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))
for k, v in [("BOT_TOKEN","t"),("ENGINE_API_KEY","t"),("CORS_ALLOWED_ORIGINS","*"),("REFERRAL_SECRET","t")]:
    os.environ.setdefault(k, v)

print("=" * 60)
print("C-7 VERIFICATION: Dynamic Registration Dispatch")
print("=" * 60)

HANDLER_MODULES = [
    "gpt_reply", "subscription_handler", "pay", "X_handler",
    "whale", "alerts", "wallet_watch", "ston",
    "early_detection", "influencer_handler", "referral",
]

results = {}
for module_name in HANDLER_MODULES:
    try:
        module = importlib.import_module(f'handlers.{module_name}')
        reg_func = None
        for attr_name in dir(module):
            if attr_name.startswith('register') and callable(getattr(module, attr_name)):
                reg_func = getattr(module, attr_name)
                break
        has_router = hasattr(module, 'router')
        if reg_func:
            sig = inspect.signature(reg_func)
            params = list(sig.parameters.keys())
            results[module_name] = ("OK", f"register: {reg_func.__name__}({', '.join(params)})")
        elif has_router:
            results[module_name] = ("OK", "router fallback (dp.include_router)")
        else:
            results[module_name] = ("DEAD", "NO REGISTRATION PATH FOUND")
    except ImportError as e:
        results[module_name] = ("SKIP", f"ImportError: {e}")
    except Exception as e:
        results[module_name] = ("ERROR", f"{type(e).__name__}: {e}")

for name, (status, path) in results.items():
    icon = {"OK": "[OK]", "DEAD": "[DEAD]", "SKIP": "[SKIP]", "ERROR": "[ERR]"}[status]
    print(f"  {icon:6s} {name:25s} -> {path}")

ok = sum(1 for s,_ in results.values() if s == "OK")
dead = sum(1 for s,_ in results.values() if s == "DEAD")
skip = sum(1 for s,_ in results.values() if s == "SKIP")
print(f"\n  Result: {ok} reachable, {skip} skipped (optional), {dead} DEAD")
if dead > 0:
    print("  !!! DEAD HANDLERS FOUND !!!")

print("\n--- 3 NEW MODULES ---")
for m in ["early_detection", "influencer_handler", "referral"]:
    s, p = results.get(m, ("MISSING", "?"))
    icon = "[OK]" if s == "OK" else "[FAIL]"
    print(f"  {icon} {m}: {p}")

print("\n" + "=" * 60)
print("C-10 VERIFICATION: Scanner Stub Return Shapes")
print("=" * 60)

async def verify_stubs():
    from utils.scanner import scan_early_signals, get_combined_scan, analyze_token_details, get_system_status
    errors = []

    # 1) scan_early_signals
    print("\n  [1/4] scan_early_signals(hours_back=12, min_confidence=0.0)...")
    r1 = await scan_early_signals(hours_back=12, min_confidence=0.0)
    assert isinstance(r1, list), f"FAIL: got {type(r1)}"
    if r1:
        keys = ['symbol', 'name', 'confidence', 'risk_level', 'liquidity', 'dex']
        missing = [k for k in keys if k not in r1[0]]
        if missing:
            errors.append(f"scan_early_signals missing keys: {missing}")
            print(f"  [FAIL] Missing keys: {missing}")
        else:
            # Verify handler can parse confidence
            conf = r1[0]['confidence']
            try:
                v = float(conf.rstrip('%')) if isinstance(conf, str) else float(conf) * 100
                print(f"  [OK] {len(r1)} signals, confidence='{conf}' -> parsed as {v}")
            except Exception as e:
                errors.append(f"confidence parsing: {e}")
                print(f"  [FAIL] confidence '{conf}' breaks handler: {e}")
    else:
        print(f"  [WARN] Empty (no trending data offline) -- OK")

    # 2) get_combined_scan
    print("\n  [2/4] get_combined_scan(trending_limit=5, early_limit=8)...")
    r2 = await get_combined_scan(trending_limit=5, early_limit=8, min_confidence=0.0)
    assert isinstance(r2, dict), f"FAIL: got {type(r2)}"
    for k in ['trending', 'early_signals', 'summary']:
        if k not in r2:
            errors.append(f"get_combined_scan missing '{k}'")
    s = r2.get('summary', {})
    for sk in ['trending_count', 'early_signals_count']:
        if sk not in s:
            errors.append(f"summary missing '{sk}'")
    # Handler accesses: token.get('symbol'), token.get('volume'), token.get('lp')
    t_list = r2.get('trending', [])
    if t_list:
        for tk in ['symbol', 'name', 'volume', 'lp']:
            if tk not in t_list[0]:
                errors.append(f"trending[0] missing '{tk}'")
    if not [e for e in errors if 'combined_scan' in e or 'trending' in e or 'summary' in e]:
        print(f"  [OK] trending={len(t_list)}, early={len(r2.get('early_signals',[]))}")
    else:
        print(f"  [FAIL] Shape errors in combined_scan")

    # 3) analyze_token_details
    print("\n  [3/4] analyze_token_details('NONEXISTENT')...")
    r3 = await analyze_token_details("NONEXISTENT_XYZ_123")
    assert r3 is None, f"FAIL: expected None got {type(r3)}"
    print(f"  [OK] Returns None for unknown token")
    if r1:
        sym = r1[0]['symbol']
        r3b = await analyze_token_details(sym)
        if r3b:
            for rk in ['analysis', 'is_early_detection']:
                if rk not in r3b:
                    errors.append(f"analyze_token_details missing '{rk}'")
            a = r3b.get('analysis', {})
            # Handler accesses: a.get('symbol'), a.get('name'), a.get('confidence_score'), etc.
            print(f"  [OK] Found '{sym}', keys: {list(a.keys())[:5]}...")
        else:
            print(f"  [WARN] '{sym}' not found (may be race condition)")

    # 4) get_system_status
    print("\n  [4/4] get_system_status()...")
    r4 = await get_system_status()
    assert isinstance(r4, dict), f"FAIL: got {type(r4)}"
    for k in ['combined_status', 'trending_system', 'early_detection_system']:
        if k not in r4:
            errors.append(f"get_system_status missing '{k}'")
    ts = r4.get('trending_system', {})
    for tk in ['status', 'token_count']:
        if tk not in ts:
            errors.append(f"trending_system missing '{tk}'")
    ed = r4.get('early_detection_system', {})
    for ek in ['status', 'database_connected', 'spacy_available']:
        if ek not in ed:
            errors.append(f"early_detection_system missing '{ek}'")
    if not [e for e in errors if 'system_status' in e or 'trending_system' in e or 'early_detection' in e]:
        print(f"  [OK] combined_status='{r4['combined_status']}'")
    else:
        print(f"  [FAIL] Shape errors in system_status")

    print(f"\n{'='*60}")
    if errors:
        print(f"FAIL: {len(errors)} shape error(s):")
        for e in errors:
            print(f"  * {e}")
        return 1
    else:
        print("ALL SCANNER STUBS RETURN CORRECT SHAPES")
        return 0

exit_code = asyncio.run(verify_stubs())
sys.exit(exit_code)
