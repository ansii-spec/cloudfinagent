"""Convert pipeline output to plain JSON (numpy -> python, NaN/inf -> None, datetime -> ISO, step tuples -> objects)."""
import math
from datetime import date, datetime, timezone

import numpy as np

STEP_KEYS = ("step", "calculation", "result")


def _float(v: float):
    return None if (math.isnan(v) or math.isinf(v)) else v


def to_jsonable(obj, _key: str | None = None):
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v, str(k)) for k, v in obj.items()}
    if _key == "steps" and isinstance(obj, (list, tuple)):
        return [dict(zip(STEP_KEYS, (to_jsonable(x) for x in s))) if isinstance(s, (list, tuple)) else to_jsonable(s)
                for s in obj]
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return _float(float(obj))
    if isinstance(obj, datetime):
        dt = obj if obj.tzinfo else obj.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(obj, date):
        return obj.isoformat()
    if obj is None or isinstance(obj, str):
        return obj
    return str(obj)
