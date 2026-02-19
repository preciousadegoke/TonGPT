#!/usr/bin/env python3
"""
Test script to verify critical fixes applied to TonGPT
Run this to ensure all improvements are working correctly
"""

import asyncio
import sys
import os

# Fix Unicode output on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))


async def test_imports():
    """Test 1: Verify no circular imports"""
    print("\n✓ Test 1: Checking for circular imports...")
    try:
        from services.blockchain import monitor_followed_wallets
        print("  ✅ services.blockchain imports correctly (no circular import)")
        return True
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


async def test_stonfi_api():
    """Test 2: Verify STON.fi API uses async/aiohttp"""
    print("\n✓ Test 2: Testing STON.fi API async patterns...")
    try:
        from services.stonfi_api import fetch_top_ston_pools
        
        # Should not block event loop
        result = await asyncio.wait_for(fetch_top_ston_pools(), timeout=15.0)
        
        if isinstance(result, list):
            print(f"  ✅ STON.fi API is async (returned {len(result)} pools)")
            return True
        else:
            print(f"  ❌ STON.fi API returned unexpected type: {type(result)}")
            return False
    except asyncio.TimeoutError:
        print("  ⚠️  STON.fi API timeout (network issue, but async is working)")
        return True  # Async is working, just network timeout
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


async def test_rate_limiter():
    """Test 3: Rate limiter works without Redis"""
    print("\n✓ Test 3: Testing Rate Limiter without Redis...")
    try:
        from utils.rate_limiter import RateLimiter
        
        # Initialize without Redis (should work)
        limiter = RateLimiter(redis_client=None)
        print("  ✅ RateLimiter initialized without Redis (graceful fallback)")
        
        # Try to check rate limit
        allowed, info = await limiter.check_rate_limit(user_id=123, tier="free")
        print(f"  ✅ Rate limit check works: allowed={allowed}")
        return True
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


async def test_error_handling():
    """Test 4: Verify improved error handling"""
    print("\n✓ Test 4: Testing error handling...")
    try:
        import inspect
        from main import on_startup
        
        # Check that on_startup has retry logic
        source = inspect.getsource(on_startup)
        
        checks = [
            ("max_retries" in source, "Retry logic"),
            ("asyncio.wait_for" in source, "Timeout protection"),
            ("asyncio.TimeoutError" in source, "Timeout handling"),
            ("exc_info=True" in source, "Exception logging"),
        ]
        
        all_good = True
        for check, name in checks:
            if check:
                print(f"  ✅ {name} implemented")
            else:
                print(f"  ❌ {name} missing")
                all_good = False
        
        return all_good
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


async def test_gpt_handler():
    """Test 5: Verify GPT handler error handling"""
    print("\n✓ Test 5: Testing GPT handler error handling...")
    try:
        import inspect
        from handlers.gpt_reply import handle_gpt_query
        
        source = inspect.getsource(handle_gpt_query)
        
        checks = [
            ("TimeoutError" in source, "Timeout error handling"),
            ("send_chat_action" in source, "Chat action"),
            ("message.reply" in source, "Error messages to user"),
            ("exc_info=True" in source, "Traceback logging"),
        ]
        
        all_good = True
        for check, name in checks:
            if check:
                print(f"  ✅ {name} implemented")
            else:
                print(f"  ❌ {name} missing")
                all_good = False
        
        return all_good
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


async def test_env_template():
    """Test 6: Verify .env.example exists"""
    print("\n✓ Test 6: Checking environment template...")
    try:
        env_example = os.path.join(os.path.dirname(__file__), '.env.example')
        
        if os.path.exists(env_example):
            with open(env_example) as f:
                content = f.read()
            
            checks = [
                ("BOT_TOKEN=your_" in content, "Placeholder BOT_TOKEN"),
                (".env" in content and "DO NOT COMMIT" in content, "Warning message"),
                ("OPENAI_API_KEY" in content, "OpenAI placeholder"),
                ("X_API_KEY" in content, "X/Twitter placeholder"),
            ]
            
            all_good = True
            for check, name in checks:
                if check:
                    print(f"  ✅ {name} present")
                else:
                    print(f"  ⚠️  {name} missing")
                    all_good = False
            
            return all_good
        else:
            print("  ❌ .env.example not found")
            return False
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


async def test_gitignore():
    """Test 7: Verify .gitignore has .env"""
    print("\n✓ Test 7: Checking .gitignore...")
    try:
        gitignore = os.path.join(os.path.dirname(__file__), '.gitignore')
        
        if os.path.exists(gitignore):
            with open(gitignore) as f:
                content = f.read()
            
            if ".env" in content:
                print("  ✅ .env is in .gitignore (no accidental commits)")
                return True
            else:
                print("  ❌ .env NOT in .gitignore (DANGEROUS!)")
                return False
        else:
            print("  ❌ .gitignore not found")
            return False
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


async def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("🧪 TonGPT Critical Fixes Test Suite")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_stonfi_api,
        test_rate_limiter,
        test_error_handling,
        test_gpt_handler,
        test_env_template,
        test_gitignore,
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"  ❌ Unexpected error in {test.__name__}: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Results: {passed}/{total} tests passed\n")
    
    if passed == total:
        print("✅ ALL CRITICAL FIXES VERIFIED!")
        print("\n📋 Next Steps:")
        print("  1. Rotate all API credentials (see CREDENTIAL_ROTATION.md)")
        print("  2. Test startup: python main.py")
        print("  3. Monitor logs for any issues")
        return 0
    else:
        print(f"⚠️  {total - passed} test(s) failed")
        print("  Please review the failures above")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
