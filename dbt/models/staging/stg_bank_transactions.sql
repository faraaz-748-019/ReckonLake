SELECT
    event_id,
    shared_ref,
    txn_id,
    amount_paise,
    state,
    payer_bank_id,
    event_date,
    timestamp_utc
FROM {{ source('raw_gold', 'transactions') }}
WHERE payer_bank_id IS NOT NULL
