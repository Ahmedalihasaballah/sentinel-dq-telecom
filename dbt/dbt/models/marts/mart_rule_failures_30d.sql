-- Dashboard: how often each gate rule failed over the last 30 days, with the owner of each rule.
-- One row per dataset + rule that failed at least once. failure_rank 1 = the rule to fix first.

with results as (
    -- 1) only the gate rules, only the last 30 days
    select dataset, rule_id, run_ts, status, severity, detail, rows_checked, rows_failed
    from {{ source('monitoring', 'dq_results') }}
    where check_name = 'gate_rule'
      and run_ts >= date_sub(current_date(), 30)
),

per_rule as (
    -- 2) one row per dataset + rule
    select
        dataset,
        rule_id,
        count(*)                                          as total_runs,
        sum(case when rows_failed > 0  then 1 else 0 end) as failed_runs,
        sum(case when status = 'FAIL'  then 1 else 0 end) as fail_runs,
        sum(case when status = 'WARN'  then 1 else 0 end) as warn_runs,
        sum(rows_checked)                                 as rows_checked,
        sum(rows_failed)                                  as rows_failed,
        max(case when rows_failed > 0 then run_ts end)    as last_failed_at
    from results
    group by dataset, rule_id
),

latest_fail as (
    -- 3) the action, severity and description from the latest run where the rule failed
    --    (taken from dq_results, because monitoring.dq_rules can be older than the contract the gate used)
    select
        dataset,
        rule_id,
        regexp_extract(detail, 'action=([a-z]+)', 1)     as action,
        severity,
        trim(substr(detail, instr(detail, ';') + 1))     as description
    from (
        select *, row_number() over (partition by dataset, rule_id order by run_ts desc) as _rn
        from results
        where rows_failed > 0
    )
    where _rn = 1
),

routing as (
    -- 4) who owns each dataset
    select dataset, team, owner
    from {{ source('monitoring', 'incident_routing') }}
    where pillar = '*'
),

joined as (
    select
        p.*,
        r.action,
        r.severity,
        r.description,
        coalesce(o.team,  d.team)  as owner_team,
        coalesce(o.owner, d.owner) as owner,
        -- weight used by priority_rank: a critical rule counts 4x a low one
        case r.severity when 'critical' then 4 when 'high' then 3 when 'medium' then 2 else 1 end as severity_weight
    from per_rule p
    left join latest_fail r on p.dataset = r.dataset and p.rule_id = r.rule_id
    left join routing o on p.dataset = o.dataset
    left join routing d on d.dataset = '*'
    where p.failed_runs > 0
)

select
    dataset,
    rule_id,
    dataset || ' · ' || rule_id                                        as rule_label,
    -- label for the chart axis: severity and action visible without hovering
    dataset || ' · ' || rule_id || '  [' || upper(coalesce(severity, '?')) || ' · ' || coalesce(action, '?') || ']'
                                                                       as chart_label,
    action,
    severity,
    description,
    owner_team,
    owner,
    total_runs,
    failed_runs,
    fail_runs,
    warn_runs,
    rows_checked,
    rows_failed,
    round(1 - rows_failed / nullif(rows_checked, 0), 4)                 as pass_rate,
    last_failed_at,
    severity_weight,
    rows_failed * severity_weight                                       as priority_score,
    -- 1 = most failed rows (the chart's ranking)
    row_number() over (order by rows_failed desc, failed_runs desc, rule_id)                   as failure_rank,
    -- 1 = most failed rows weighted by severity (alternative view: what hurts most)
    row_number() over (order by rows_failed * severity_weight desc, rows_failed desc, rule_id) as priority_rank
from joined
