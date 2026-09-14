"""Authenticated checkout routes; all activation stays in the existing bot/monitor."""
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field
from services import checkout
import os


class TonQuoteBody(BaseModel):
    plan: str = Field(max_length=32)
    sender: str = Field(max_length=128)


class StarsBody(BaseModel):
    plan: str = Field(max_length=32)


class StatusBody(BaseModel):
    token: str = Field(max_length=4096)
    message_hash: str | None = Field(default=None, pattern=r'^[0-9a-fA-F]{64}$')


def install_checkout_routes(app, verify_init_data):
    def authenticate(request, response):
        response.headers['Cache-Control'] = 'no-store'
        if not os.getenv('BOT_TOKEN'):
            raise HTTPException(503, 'Telegram authentication is not configured')
        try:
            return verify_init_data(request.headers.get('X-Telegram-Init-Data', ''))['id']
        except (ValueError, KeyError):
            raise HTTPException(401, 'Invalid Telegram init data')

    @app.get('/api/checkout/config')
    async def config(request: Request, response: Response):
        authenticate(request, response)
        try:
            return checkout.ton_config()
        except ValueError as exc:
            return {'enabled': False, 'error': str(exc)}

    @app.post('/api/checkout/ton')
    async def ton_quote(body: TonQuoteBody, request: Request, response: Response):
        user_id = authenticate(request, response)
        try:
            return checkout.ton_quote(user_id, body.plan, body.sender)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError:
            raise HTTPException(503, 'Checkout signing is not configured')

    @app.post('/api/checkout/stars')
    async def stars(body: StarsBody, request: Request, response: Response):
        user_id = authenticate(request, response)
        try:
            ticket = checkout.stars_ticket(user_id, body.plan)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError:
            raise HTTPException(503, 'Checkout signing is not configured')
        from core.bot_instance import get_bot
        from core.pricing import PLANS
        from aiogram.types import LabeledPrice
        bot = get_bot()
        if bot is None:
            raise HTTPException(503, 'Bot not ready')
        plan = PLANS[body.plan]
        try:
            url = await bot.create_invoice_link(
                title=f"TonGPT {plan['name']}", description=f"Upgrade to {plan['name']} (1 month).",
                payload=checkout.invoice_payload(ticket), provider_token='', currency='XTR',
                prices=[LabeledPrice(label=plan['name'], amount=plan['price_stars'])],
            )
        except Exception:
            raise HTTPException(502, 'Could not create invoice')
        if not url:
            raise HTTPException(502, 'Invoice service returned no URL')
        return {**ticket, 'invoice_url': url}

    @app.post('/api/checkout/status')
    async def status(body: StatusBody, request: Request, response: Response):
        user_id = authenticate(request, response)
        try:
            ticket = checkout.read_ticket(body.token, user_id)
        except ValueError:
            raise HTTPException(403, 'Checkout is invalid, expired, or belongs to another user')
        except RuntimeError:
            raise HTTPException(503, 'Checkout signing is not configured')
        try:
            return await checkout.checkout_status(ticket, body.message_hash)
        except Exception:
            raise HTTPException(503, 'Could not confirm activation; do not pay again. Retry the status check.')
