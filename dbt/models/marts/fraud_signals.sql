WITH fan_in AS (
    SELECT
        payee_vpa_token,
        COUNT(DISTINCT payer_vpa_token) AS distinct_payers,
        COUNT(*) AS inbound_count,
        SUM(amount_paise) / 100.0 AS inbound_rupees
    FROM {{ ref('stg_psp_transactions') }}
    GROUP BY 1
),

velocity AS (
    SELECT
        payer_vpa_token,
        event_date,
        COUNT(*) AS daily_txn_count,
        SUM(amount_paise) / 100.0 AS daily_spend_rupees
    FROM {{ ref('stg_psp_transactions') }}
    GROUP BY 1, 2
)

SELECT
    f.payee_vpa_token AS vpa_token,
    f.distinct_payers AS fan_in_degree,
    f.inbound_count,
    f.inbound_rupees,
    COALESCE(v.daily_txn_count, 0) AS max_payer_velocity
FROM fan_in AS f
LEFT JOIN velocity AS v
    ON f.payee_vpa_token = v.payer_vpa_token
WHERE f.distinct_payers >= 5 OR COALESCE(v.daily_txn_count, 0) >= 10
