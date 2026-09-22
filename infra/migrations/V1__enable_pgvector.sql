-- IF NOT EXISTS also handles local volumes created by the former init script.
-- Qualify application objects: Flyway history lives in a separate schema.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
