# 🚨 URGENT: CREDENTIAL ROTATION CHECKLIST

**Your API keys were exposed. Complete these steps IMMEDIATELY:**

## Step 1: Rotate All Credentials

### Telegram Bot
- [ ] Go to https://t.me/BotFather
- [ ] Select `/mybots` → Your Bot → `API Token`
- [ ] Click "Regenerate token"
- [ ] Copy new token
- [ ] Update `.env`: `BOT_TOKEN=YOUR_NEW_TOKEN`

### OpenAI
- [ ] Go to https://platform.openai.com/account/api-keys
- [ ] Delete old key
- [ ] Create new key
- [ ] Update `.env`: `OPENAI_API_KEY=sk-...`

### OpenRouter (if used)
- [ ] Go to https://openrouter.ai/keys
- [ ] Delete old key
- [ ] Create new key
- [ ] Update `.env`: `OPENROUTER_API_KEY=sk-or-...`

### X/Twitter
- [ ] Go to https://developer.twitter.com/en/portal/dashboard
- [ ] Regenerate ALL keys:
  - [ ] API Key
  - [ ] API Secret
  - [ ] Access Token
  - [ ] Access Token Secret
  - [ ] Bearer Token
- [ ] Update `.env` with all new values

### TON API
- [ ] Go to https://tonapi.io
- [ ] Request new API key
- [ ] Update `.env`: `TON_API_KEY=...`

### Payment Token (Telegram)
- [ ] Go to https://pay.telegram.org
- [ ] Create new payment provider token
- [ ] Update `.env`: `PAYMENT_TOKEN=...`

### Redis
- [ ] Go to your Redis provider (AWS/Azure/Local)
- [ ] Change password
- [ ] Update `.env`: `REDIS_PASSWORD=...`

---

## Step 2: Clean Git History

If you ever pushed `.env` to GitHub/GitLab:

```bash
# Completely remove .env from history
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch .env" \
  --prune-empty --tag-name-filter cat -- --all

# Force push (only if private repo!)
git push origin --force --all
git push origin --force --tags
```

Or simply delete and recreate the repository if preferred.

---

## Step 3: Verify .env Setup

```bash
# ✓ Copy template
cp .env.example .env

# ✓ Edit with new credentials (NEVER commit this)
nano .env
# or
code .env

# ✓ Verify .env is in .gitignore
cat .gitignore | grep ".env"
# Should show: .env
```

---

## Step 4: Test New Credentials

```bash
# Start the bot (will try 3 times to connect)
python main.py

# You should see:
# 🚀 TonGPT initialization starting...
# 📦 Initializing services...
# ✅ ...
# 🤖 TonGPT is now running with enhanced capabilities!
```

---

## Step 5: Monitor for Anomalies

After deploying with new credentials:

```bash
# Check for unauthorized usage of old credentials
# - OpenAI: Check usage logs at platform.openai.com
# - X: Check access logs at developer.twitter.com
# - Telegram: Check bot logs
# - TON: Check API usage
```

**Report any unauthorized usage to the respective platforms immediately.**

---

## ✅ Verification Commands

```bash
# Test each service connection:

# 1. Test Telegram (will fail if token wrong)
python -c "from aiogram import Bot; print('Telegram: OK')"

# 2. Test OpenAI
python -c "import openai; print('OpenAI: OK')"

# 3. Test Redis
python -c "import redis; r = redis.Redis(); r.ping(); print('Redis: OK')"

# 4. Test X/Twitter  
python -c "import tweepy; print('Tweepy: OK')"
```

---

## 🔒 Security Best Practices Going Forward

1. **Never commit secrets** - Use .env.example for templates
2. **Use environment-specific configs** - Keep .env, .env.staging, .env.prod separate
3. **Rotate credentials regularly** - Every 3-6 months
4. **Monitor usage** - Check API usage dashboards weekly
5. **Enable 2FA** - On all provider accounts (OpenAI, Twitter, etc.)
6. **Use service accounts** - Create dedicated service accounts for each bot
7. **Implement audit logging** - Log all credential usage

---

## 📞 If Compromised

If you suspect credentials were accessed by unauthorized parties:

1. **Rotate immediately** ✓ (following above)
2. **Check usage logs** - Look for strange API calls
3. **File reports** - Alert OpenAI, Twitter, Telegram, TON team
4. **Enable monitoring** - Set up alerts for unusual usage
5. **Review code** - Check if any malicious code was injected
6. **Update dependencies** - Run `pip install --upgrade -r requirements.txt`

---

**Status**: Awaiting credential rotation ⏳

**Remember**: Never share `.env` with anyone, ever. Always use `.env.example` for templates.
