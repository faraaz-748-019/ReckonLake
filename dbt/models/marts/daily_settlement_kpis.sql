SELECT
    event_date,
    psp_app,
    payer_bank_id,
    COUNT(*) AS total_transactions,
    ROUND(SUM(amount_paise) / 100.0, 2) AS total_amount_rupees,
    SUM(
        CASE WHEN state = 'SUCCESS' THEN 1 ELSE 0 END
    ) AS successful_transactions,
    SUM(
        CASE WHEN state = 'FAILED' THEN 1 ELSE 0 END
    ) AS failed_transactions,
    ROUND(
        100.0 * SUM(CASE WHEN state = 'SUCCESS' THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0),
        2
    ) AS success_rate_pct
FROM {{ ref('stg_psp_transactions') }}
GROUP BY 1, 2, 3
