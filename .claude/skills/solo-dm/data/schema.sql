-- Solo DM canonical state.
-- Invariants:
--   1. turns are append-only after a roll lands (enforced via trigger).
--   2. events are append-only.
--   3. retcons reference a prior turn; they do not mutate it.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS campaigns (
  id            INTEGER PRIMARY KEY,
  slug          TEXT    NOT NULL UNIQUE,
  name          TEXT    NOT NULL,
  vault_path    TEXT    NOT NULL,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  settings_json TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS characters (
  id                    INTEGER PRIMARY KEY,
  campaign_id           INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  name                  TEXT,
  kind                  TEXT    NOT NULL CHECK (kind IN ('pc','named_npc','mook')),
  model_tier            TEXT    CHECK (model_tier IN ('opus','sonnet','haiku')),
  sheet_json            TEXT    NOT NULL DEFAULT '{}',
  current_hp            INTEGER,
  temp_hp               INTEGER DEFAULT 0,
  conditions_json       TEXT    NOT NULL DEFAULT '[]',
  disposition           TEXT,
  last_seen_session_id  INTEGER REFERENCES sessions(id),
  last_seen_location_id INTEGER REFERENCES locations(id),
  promoted_from_mook    INTEGER NOT NULL DEFAULT 0,
  promotion_reason      TEXT,
  promotion_turn_id     INTEGER REFERENCES turns(id),
  created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS locations (
  id                 INTEGER PRIMARY KEY,
  campaign_id        INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  name               TEXT    NOT NULL,
  description        TEXT,
  region             TEXT,
  faction_id         INTEGER REFERENCES factions(id),
  parent_location_id INTEGER REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS factions (
  id            INTEGER PRIMARY KEY,
  campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  name          TEXT    NOT NULL,
  posture       TEXT,
  goals_json    TEXT    NOT NULL DEFAULT '[]',
  public_face   TEXT,
  secret_agenda TEXT
);

CREATE TABLE IF NOT EXISTS quests (
  id                  INTEGER PRIMARY KEY,
  campaign_id         INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  name                TEXT    NOT NULL,
  status              TEXT    NOT NULL CHECK (status IN ('active','complete','failed','dormant')),
  beats_json          TEXT    NOT NULL DEFAULT '[]',
  giver_character_id  INTEGER REFERENCES characters(id),
  source_session_id   INTEGER REFERENCES sessions(id),
  created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  id          INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  number      INTEGER NOT NULL,
  started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  ended_at    TEXT,
  prep_json   TEXT    NOT NULL DEFAULT '{}',
  recap_md    TEXT,
  scene_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE (campaign_id, number)
);

CREATE TABLE IF NOT EXISTS scenes (
  id             INTEGER PRIMARY KEY,
  session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  ord            INTEGER NOT NULL,
  name           TEXT    NOT NULL,
  location_id    INTEGER REFERENCES locations(id),
  summary        TEXT,
  npc_goals_json TEXT    NOT NULL DEFAULT '[]',
  opened_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  closed_at      TEXT
);

CREATE TABLE IF NOT EXISTS turns (
  id                         INTEGER PRIMARY KEY,
  session_id                 INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  scene_id                   INTEGER REFERENCES scenes(id),
  ord                        INTEGER NOT NULL,
  actor_character_id         INTEGER REFERENCES characters(id),
  action_text                TEXT    NOT NULL,
  classification             TEXT    NOT NULL CHECK (classification IN ('narrative','check','attack','save','social','damage_dealt')),
  target_number              INTEGER,
  advantage                  TEXT    NOT NULL DEFAULT 'none' CHECK (advantage IN ('none','adv','dis')),
  reasoning                  TEXT,
  rule_of_cool_original_dc   INTEGER,
  rule_of_cool_reason        TEXT,
  committed_at               TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rolls (
  id         INTEGER PRIMARY KEY,
  turn_id    INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  spec       TEXT    NOT NULL,
  rolls_json TEXT    NOT NULL,
  total      INTEGER NOT NULL,
  outcome    TEXT    CHECK (outcome IN ('crit','pass','fail','crit_fail')),
  rolled_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- A turn cannot be mutated once a roll has landed against it.
CREATE TRIGGER IF NOT EXISTS turns_no_edit_after_roll
BEFORE UPDATE ON turns
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM rolls WHERE turn_id = OLD.id)
BEGIN
  SELECT RAISE(ABORT, 'turn is sealed: a roll has landed. Use a retcon event.');
END;

CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY,
  session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id     INTEGER REFERENCES turns(id),
  type        TEXT    NOT NULL CHECK (type IN (
                'damage','heal','xp','loot','condition_add','condition_remove',
                'quest_advance','quest_add','quest_complete','discovery',
                'retcon','house_rule','npc_promotion','scene_open','scene_close',
                'session_open','session_close','note'
              )),
  data_json   TEXT    NOT NULL DEFAULT '{}',
  occurred_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TABLE IF NOT EXISTS npc_memory (
  id                INTEGER PRIMARY KEY,
  character_id      INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  fact              TEXT    NOT NULL,
  learned_in_turn_id INTEGER REFERENCES turns(id),
  salience          INTEGER NOT NULL DEFAULT 3 CHECK (salience BETWEEN 1 AND 5),
  last_referenced   TEXT    NOT NULL DEFAULT (datetime('now')),
  created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS world_state (
  id          INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  key         TEXT    NOT NULL,
  value       TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (campaign_id, key)
);

CREATE TABLE IF NOT EXISTS relationships (
  npc_a_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  npc_b_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  kind     TEXT    NOT NULL,
  notes    TEXT,
  PRIMARY KEY (npc_a_id, npc_b_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, ord);
CREATE INDEX IF NOT EXISTS idx_turns_scene ON turns(scene_id, ord);
CREATE INDEX IF NOT EXISTS idx_rolls_turn ON rolls(turn_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_npc_memory_char ON npc_memory(character_id, salience DESC);
CREATE INDEX IF NOT EXISTS idx_scenes_session ON scenes(session_id, ord);
CREATE INDEX IF NOT EXISTS idx_characters_campaign ON characters(campaign_id, kind);
