-- Verify no raw '@' VPA identifier leaks into fraud_signals mart
SELECT vpa_token
FROM {{ ref('fraud_signals') }}
WHERE vpa_token LIKE '%@%'
