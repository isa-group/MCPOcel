# inspect_store.py

from shared.store.jsonl_store import TelemetryStore

store = TelemetryStore.open("data/telemetry.jsonl")

print("\nTOTAL EVENTS")
print(store.count())

print("\nCURRENT BUCKETS")
for snap in store.all_bucket_snapshots():
    print(
        snap.api_target,
        snap.bucket_id,
        snap.remaining,
        "/",
        snap.limit
    )

print("\nLAST EVENTS")
for row in store.tail(10):
    print(
        row["timestamp_utc"],
        row["status_code"],
        row["bucket_id"]
    )

store.close()