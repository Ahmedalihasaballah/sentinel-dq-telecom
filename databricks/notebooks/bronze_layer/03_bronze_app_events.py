# Databricks notebook source
# BRONZE APP EVENTS: load the mobile app events that bridge.py wrote to the Volume into bronze.app_events_raw.
#   source  /Volumes/data_sentinel/bronze/raw/app_events/app_events_<time>.jsonl  (one Kafka message per line, topic app.events)
#   target  data_sentinel.bronze.app_events_raw                                   (one row per Kafka message)
# Producer: kafka/app_event_producer.py (streaming source) -> Kafka topic app.events -> bridge.py -> Volume.
# Safe to run again: only messages not stored yet are inserted. Key = topic + partition + offset + Kafka timestamp,
# so events of a recreated topic (offsets restart at 0) are not mistaken for old ones. Parsing happens in the quality gate.

from pyspark.sql import functions as F
from delta.tables import DeltaTable

APP_DIR = "/Volumes/data_sentinel/bronze/raw/app_events"
TARGET_TABLE = "data_sentinel.bronze.app_events_raw"

try:
    files = [f for f in dbutils.fs.ls(APP_DIR) if f.name.endswith(".jsonl")]
except Exception:
    files = []
if not files:
    dbutils.notebook.exit("no app event files in the Volume yet (run app_event_producer.py and bridge.py): nothing to load")
print(f"Found {len(files)} app event files")

bronze_df = (
    spark.read.json(f"{APP_DIR}/*.jsonl")
    .withColumn("_source_file", F.col("_metadata.file_path"))
    .withColumn("_bronze_ingested_at", F.current_timestamp())
    .dropDuplicates(["topic", "partition", "offset", "kafka_timestamp_ms"])
)

before = spark.table(TARGET_TABLE).count() if spark.catalog.tableExists(TARGET_TABLE) else 0
if not spark.catalog.tableExists(TARGET_TABLE):
    bronze_df.write.format("delta").mode("overwrite").saveAsTable(TARGET_TABLE)
else:
    (DeltaTable.forName(spark, TARGET_TABLE).alias("t")
        .merge(bronze_df.alias("s"), "t.topic = s.topic AND t.partition = s.partition AND t.offset = s.offset "
               "AND t.kafka_timestamp_ms <=> s.kafka_timestamp_ms")
        .whenNotMatchedInsertAll()
        .execute())

after = spark.table(TARGET_TABLE).count()
print(f"bronze.app_events_raw: {before:,} -> {after:,} rows ({after - before:,} new)")

# Peek inside the newest raw messages (typed columns are built by the quality gate)
display(
    spark.table(TARGET_TABLE)
    .select("offset", "kafka_timestamp_ms",
            F.get_json_object("value", "$.event_id").alias("event_id"),
            F.get_json_object("value", "$.customer_id").alias("customer_id"),
            F.get_json_object("value", "$.event_type").alias("event_type"),
            F.get_json_object("value", "$.app_version").alias("app_version"),
            F.get_json_object("value", "$.event_ts").alias("event_ts"))
    .orderBy(F.col("kafka_timestamp_ms").desc())
    .limit(10)
)
