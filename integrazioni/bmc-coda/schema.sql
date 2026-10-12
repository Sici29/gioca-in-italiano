CREATE TABLE IF NOT EXISTS contributions (
  record_key TEXT PRIMARY KEY,
  project_id TEXT,
  supporter_key TEXT,
  state TEXT NOT NULL,
  event_time INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS contributions_project ON contributions(project_id, state);
CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
