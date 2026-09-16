# Tier notifications and quieter storage

New tier applications notify only tiercheck (1549336543527960636) in the tier's parent channel, with a link to the private application. Form details remain private. Review authorization remains High, Deputy and Leader; tiercheck alone grants no review permission. The current five-field form and tier-dependent MCL requirement are preserved.

Automatic snapshots are attempted at most once every 60 seconds per guild. Multiple updates are combined into one snapshot; unchanged snapshots make no Discord requests. Manual /backup_now and graceful shutdown bypass this interval. A sudden process loss can lose roughly the latest minute of changes; Discord outages can extend that window. Existing snapshots are retained.

Human-readable changes are sent as one compact summary per snapshot. Large summaries include the complete text as an attachment instead of a stream of messages. A failed log is retried without re-uploading an already verified identical snapshot. Pending human-readable logs live in memory; the verified snapshot remains the restoration source.
