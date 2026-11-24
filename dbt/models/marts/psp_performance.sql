SELECT
    psp_app,
    COUNT(*) AS txn_volume,
    SUM(CASE WHEN state = 'SUCCESS' THEN 1 ELSE 0 END) AS success_count,
    SUM(CASE WHEN state = 'FAILED' THEN 1 ELSE 0 END) AS failure_count,
    ROUND(100.0 * SUM(CASE WHEN state = 'SUCCESS' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS approval_rate_pct,
    ROUND(AVG(amount_paise) / 100.0, 2) AS avg_ticket_rupees
FROM {{ ref('stg_psp_transactions') }}
GROUP BY 1
