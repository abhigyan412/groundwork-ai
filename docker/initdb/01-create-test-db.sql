-- Runs once, on first start of an empty `db` volume.
-- A separate database for pytest; the tests truncate it, so it is never the dev database.
CREATE DATABASE groundwork_test OWNER groundwork;
