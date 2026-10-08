
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from kafka import KafkaConsumer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("datasentinel-bridge")

HOST = os.getenv("DATABRICKS_HOST", "").rstrip("/")
TOKEN = os.getenv("DATABRICKS_TOKEN", "")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")

VOLUME_PATH = "/Volumes/datasentinel/bronze/raw"
BATCH_SIZE = 100
FLUSH_SECONDS = 10

TOPICS = [
    "telecom.crm.customers",
    "telecom.crm.devices",
    "telecom.crm.plans",
    "telecom.billing.accounts",
    "telecom.billing.invoices",
    "telecom.billing.invoice_lines",
    "telecom.billing.payments",
]


def upload_batch(events):
    if not events:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"cdc_{timestamp}.jsonl"
    file_path = f"{VOLUME_PATH}/{filename}"

    url = f"{HOST}/api/2.0/fs/files{quote(file_path, safe='/')}"

    payload = "".join(
        json.dumps(event, ensure_ascii=False) + "\n"
        for event in events
    ).encode("utf-8")

    response = requests.put(
        url,
        params={"overwrite": "false"},
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/octet-stream",
        },
        data=payload,
        timeout=60,
    )
    response.raise_for_status()

    log.info("Uploaded %s events to %s", len(events), file_path)


def main():
    if not HOST or not TOKEN:
        raise RuntimeError(
            "Set DATABRICKS_HOST and DATABRICKS_TOKEN in .env"
        )

    # Create the destination directory if it does not exist.
    directory_url = (
        f"{HOST}/api/2.0/fs/directories"
        f"{quote(VOLUME_PATH, safe='/')}/"
    )
    response = requests.put(
        directory_url,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )
    response.raise_for_status()

    consumer = KafkaConsumer(
        *TOPICS,
        bootstrap_servers=KAFKA_BOOTSTRAP.split(","),
        group_id="datasentinel-bridge",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        consumer_timeout_ms=1000,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
    )

    events = []
    last_flush = time.monotonic()

    log.info("Bridge started; listening to %s topics", len(TOPICS))

    try:
        while True:
            records = consumer.poll(timeout_ms=1000)

            for topic_partition, messages in records.items():
                for message in messages:
                    events.append({
                        "topic": message.topic,
                        "partition": message.partition,
                        "offset": message.offset,
                        "key": (
                            message.key.decode("utf-8", errors="replace")
                            if message.key else None
                        ),
                        "value": message.value,
                        "kafka_timestamp_ms": message.timestamp,
                        "ingested_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    })

            elapsed = time.monotonic() - last_flush

            if events and (
                len(events) >= BATCH_SIZE or elapsed >= FLUSH_SECONDS
            ):
                # Commit offsets only after a successful upload.
                upload_batch(events)
                consumer.commit()
                events.clear()
                last_flush = time.monotonic()

    except KeyboardInterrupt:
        log.info("Stopping bridge")

    finally:
        # Upload remaining events before exiting.
        if events:
            upload_batch(events)
            consumer.commit()
        consumer.close()


if __name__ == "__main__":
    main()
