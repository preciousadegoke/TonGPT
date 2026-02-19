# API Security Implementation Plan

## Goal
Protect the C# Engine's internal API from unauthorized access.
Only the **Python Bot** and **MiniApp** (backend-to-backend) should be able to call sensitive endpoints.

## Strategy: API Key Authentication
We will use a simple `X-API-Key` header for authentication.
This is sufficient because the Engine is running in a private Docker network (or localhost for dev) and is not exposed to the public internet directly (behind Nginx/Firewall).

### 1. C# Backend (`TonGPT.Engine`)
- **Middleware**: Create `ApiKeyMiddleware.cs`.
- **Logic**: Check for `X-API-Key` header in request.
    - If missing or invalid -> `401 Unauthorized`.
- **Configuration**: Store valid key in `appsettings.json` (Env Var `ENGINE_API_KEY`).
- **Scope**: Apply to **ALL** endpoints (Global Filter) or specific controllers.
    - *Decision*: Apply Globally for simplicity, maybe exempt `Swagger` (dev only) or `HealthCheck`.

### 2. Python Bot (`services/engine_client.py`)
- Update `EngineClient` to inject `X-API-Key` header in every request.
- Load key from `.env` (`ENGINE_API_KEY`).

### 3. Verification
- Test `verify_api.py` (expect failure without key).
- Update `verify_api.py` to include key -> Success.

## Plan
1.  Add `ApiKey` to `appsettings.json` and `.env`.
2.  Implement `ApiKeyMiddleware` in C#.
3.  Register Middleware in `Program.cs`.
4.  Update Python Client.
5.  Verify.
