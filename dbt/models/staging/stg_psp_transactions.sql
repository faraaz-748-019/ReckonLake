SELECT
    event_id,
    shared_ref,
    txn_id,
    txn_type,
    state,
    amount_paise,
    payer_vpa_token,
    payee_vpa_token,
    psp_app,
    payer_bank_id,
    failure_code,
    event_date,
    timestamp_utc
FROM {{ source('raw_gold', 'transactions') }}
WHERE psp_app IS NOT NULL
