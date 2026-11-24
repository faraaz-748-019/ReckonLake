SELECT
    batch_date,
    source,
    completeness,
    validity,
    uniqueness,
    timeliness,
    consistency,
    overall_score,
    gate_passed
FROM {{ source('raw_gold', 'dq_scores') }}
