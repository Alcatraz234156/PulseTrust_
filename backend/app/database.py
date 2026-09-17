from supabase import create_client, Client
from app.config import settings
from typing import List, Optional

def get_supabase_client() -> Client:
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("Supabase is not configured. Missing SUPABASE_URL or SUPABASE_KEY.")
    return create_client(settings.supabase_url, settings.supabase_key)

def insert_sensor_reading(reading_data: dict) -> dict:
    supabase = get_supabase_client()
    response = supabase.table("sensor_readings").insert(reading_data).execute()
    return response.data[0] if response.data else None

def get_latest_sensor_reading(device_id: Optional[str] = None) -> Optional[dict]:
    supabase = get_supabase_client()
    query = supabase.table("sensor_readings").select("*").order("recorded_at", desc=True).limit(1)
    if device_id:
        query = query.eq("device_id", device_id)
    response = query.execute()
    return response.data[0] if response.data else None

def get_sensor_readings(device_id: Optional[str] = None, limit: int = 50) -> List[dict]:
    supabase = get_supabase_client()
    # Ensure limit doesn't exceed a reasonable maximum
    limit = min(limit, 500)
    query = supabase.table("sensor_readings").select("*").order("recorded_at", desc=True).limit(limit)
    if device_id:
        query = query.eq("device_id", device_id)
    response = query.execute()
    return response.data
