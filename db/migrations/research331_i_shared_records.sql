-- Run separately from gameplay transactions: MySQL DDL implicitly commits.
-- Private server state, no recovered gameplay/wire schema. Existing players unchanged.
CREATE TABLE IF NOT EXISTS shared_records (
  namespace   VARBINARY(64)  NOT NULL,
  record_key  VARBINARY(128) NOT NULL,
  state_json  JSON          NULL,
  revision    BIGINT UNSIGNED NOT NULL DEFAULT 0,
  updated_at  DOUBLE        NOT NULL,
  PRIMARY KEY (namespace, record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
