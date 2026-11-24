-- Custom dbt test: verify reconciliation totals conserve every transaction
SELECT
    recon_date,
    psp_app,
    payer_bank_id,
    total_transactions,
    matched_count,
    break_count
FROM {{ ref('recon_dashboard') }}
WHERE total_transactions != (matched_count + break_count)
