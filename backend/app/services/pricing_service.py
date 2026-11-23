"""Linux on-demand list prices from the AWS Pricing API (pricing:GetProducts), cached in price_cache (7-day TTL).

Every price in the app goes through get_price(), using the platform identity (PLATFORM_AWS_ACCESS_KEY_ID/SECRET
or the instance/task role). There is no hard-coded price list: if the API cannot answer, the price is unknown
(None) and the UI shows no estimate. Failed lookups are never cached, so granting the permission later works."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import PriceCache
from app.pipeline import detector as d

log = logging.getLogger("pricing")
TTL = timedelta(days=7)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _default_client():
    from app.services import aws_session
    return aws_session.platform_session().client("pricing", region_name="us-east-1",  # Pricing API is us-east-1
                                                 config=aws_session.BOTO_CFG)


def _fetch(pricing_client, instance_type: str, region: str) -> float | None:
    price = d.hourly_price(pricing_client, instance_type, region)
    if price is None:
        d._price_cache.pop((instance_type, region), None)  # don't remember failures in-process either
    return price


def get_price(instance_type: str | None, region: str, pricing_client=None, db: Session | None = None) -> float | None:
    if not instance_type:
        return None
    own = db is None
    db = db or SessionLocal()
    try:
        row = db.get(PriceCache, (instance_type, region))
        if row and row.hourly_usd is not None and datetime.now(timezone.utc) - _aware(row.fetched_at) < TTL:
            return float(row.hourly_usd)
        price = _fetch(pricing_client or _default_client(), instance_type, region)
        if price is None:
            log.warning("Pricing API returned no price for %s/%s", instance_type, region)
            return float(row.hourly_usd) if row and row.hourly_usd is not None else None  # stale beats nothing
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
