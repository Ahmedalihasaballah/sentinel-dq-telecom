#!/usr/bin/env bash
# Registers the Debezium Postgres connector that captures the CRM and billing tables into Kafka.
#   POSTGRES_PASSWORD=... bash debezium/scripts/register_connector.sh          (Kafka Connect on localhost:8083)
# Topics: telecom.crm.<table> and telecom.billing.<table>; JSON with the schema embedded; NUMERIC as text ("51.56");
# timestamps as ISO text. These match the events already in data_sentinel.bronze.cdc_events.
# SNAPSHOT_MODE=no_data (default) resumes from the existing replication slot without re-sending the existing rows;
# use SNAPSHOT_MODE=initial only on a fresh setup (empty Bronze), or every row is loaded again.
set -euo pipefail
CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
SNAPSHOT_MODE="${SNAPSHOT_MODE:-no_data}"

curl -sS -X PUT -H "Content-Type: application/json" "$CONNECT_URL/connectors/telecom-postgres/config" -d @- <<EOF
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "database.hostname": "postgres",
  "database.port": "5432",
  "database.user": "postgres",
  "database.password": "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}",
  "database.dbname": "telecom",
  "topic.prefix": "telecom",
  "schema.include.list": "crm,billing",
  "plugin.name": "pgoutput",
  "slot.name": "debezium_slot",
  "publication.name": "dbz_publication",
  "publication.autocreate.mode": "disabled",
  "snapshot.mode": "${SNAPSHOT_MODE}",
  "decimal.handling.mode": "string",
  "key.converter": "org.apache.kafka.connect.json.JsonConverter",
  "key.converter.schemas.enable": "true",
  "value.converter": "org.apache.kafka.connect.json.JsonConverter",
  "value.converter.schemas.enable": "true"
}
EOF
echo
curl -sS "$CONNECT_URL/connectors/telecom-postgres/status"
echo
