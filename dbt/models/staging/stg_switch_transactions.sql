SELECT
    shared_ref,
    txn_id,
    amount_paise,
    state,
    event_date,
    timestamp_utc
FROM {{ source('raw_gold', 'transactions') }}
