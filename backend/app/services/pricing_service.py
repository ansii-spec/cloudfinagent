"""Linux on-demand list prices: platform credentials -> Pricing API, persisted in price_cache (7-day TTL)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import PriceCache
from app.pipeline import catalog
from app.pipeline import detector as d

TTL = timedelta(days=7)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_price(instance_type: str, region: str, pricing_client=None, db: Session | None = None) -> float | None:
    if get_settings().demo_mode or pricing_client is None:
        return catalog.price(instance_type, region)
    own = db is None
    db = db or SessionLocal()
    try:
        row = db.get(PriceCache, (instance_type, region))
        if row and datetime.now(timezone.utc) - _aware(row.fetched_at) < TTL:
            return float(row.hourly_usd) if row.hourly_usd is not None else None
        price = d.hourly_price(pricing_client, instance_type, region)
        if row is None:
            row = PriceCache(instance_type=instance_type, region=region)
            db.add(row)
        row.hourly_usd, row.fetched_at = price, datetime.now(timezone.utc)
        db.commit()
        return price
    finally:
        if own:
            db.close()


def price_fn_for(region: str, pricing_client=None):
    return lambda t: get_price(t, region, pricing_client)
