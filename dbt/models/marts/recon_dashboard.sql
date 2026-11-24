SELECT
    recon_date,
    psp_app,
    payer_bank_id,
    total_transactions,
    matched_count,
    break_count,
    quarantined_count,
    ROUND(100.0 * matched_count / NULLIF(total_transactions, 0), 2) AS match_rate_pct
FROM {{ source('raw_gold', 'recon_summary') }}
