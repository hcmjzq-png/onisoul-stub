-- Preview exact duplicate nonempty names before applying. If any exist, this
-- ALTER fails instead of renaming players or discarding a save. Back up first.
-- Binary comparison: no speculative case/accent folding of original names.
ALTER TABLE players
  ADD COLUMN username_key VARBINARY(512) GENERATED ALWAYS AS
    (CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(state_json, '$.entity.username')), '') AS BINARY)) STORED,
  ADD UNIQUE KEY uk_players_username (username_key);
