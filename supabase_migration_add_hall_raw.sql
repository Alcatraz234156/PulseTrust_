-- Run this only if sensor_readings already exists from the earlier schema.
ALTER TABLE sensor_readings
ADD COLUMN IF NOT EXISTS hall_raw integer NOT NULL DEFAULT 0;
