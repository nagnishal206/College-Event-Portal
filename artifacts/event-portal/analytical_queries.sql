-- =====================================================================
-- College Event Intelligence Portal - Analytical SQL Queries
-- =====================================================================
-- These are the FIVE complex analytical queries required by the academic
-- deliverable. Each one demonstrates a different SQL technique:
--   1. Multi-table JOIN + GROUP BY + HAVING + ORDER BY
--   2. Subquery + window function (RANK)
--   3. Aggregate + percentage computation across categories
--   4. Window function over partitions (winners per competition)
--   5. Conditional aggregation + correlated subquery for trend analysis
--
-- All queries are read-only and safe to execute in production. They are
-- referenced by the admin analytics dashboard and can also be run ad-hoc
-- via psql / pgAdmin.
-- =====================================================================


-- =====================================================================
-- Q1. Most popular APPROVED events with department breakdown
-- ---------------------------------------------------------------------
-- Returns the top 10 approved events ranked by registration count, plus
-- which department contributed the most attendees per event.
-- =====================================================================
WITH event_regs AS (
    SELECT
        e.id              AS event_id,
        e.name            AS event_name,
        e.category,
        e.date,
        e.venue,
        COUNT(r.id)       AS registrations
    FROM events e
    LEFT JOIN registrations r ON r.event_id = e.id
    WHERE e.status = 'APPROVED'
    GROUP BY e.id
    HAVING COUNT(r.id) > 0
),
top_dept_per_event AS (
    SELECT DISTINCT ON (r.event_id)
        r.event_id,
        u.department      AS top_department,
        COUNT(*)          AS dept_count
    FROM registrations r
    JOIN users u ON u.id = r.user_id
    GROUP BY r.event_id, u.department
    ORDER BY r.event_id, COUNT(*) DESC
)
SELECT
    er.event_name,
    er.category,
    er.date,
    er.venue,
    er.registrations,
    td.top_department,
    td.dept_count
FROM event_regs er
LEFT JOIN top_dept_per_event td ON td.event_id = er.event_id
ORDER BY er.registrations DESC, er.date ASC
LIMIT 10;


-- =====================================================================
-- Q2. Top participants ranked with a window function
-- ---------------------------------------------------------------------
-- Lists the 15 most active students with their registration count and
-- a dense rank (so ties share the same rank position).
-- =====================================================================
SELECT
    rnk,
    name,
    email,
    department,
    registrations
FROM (
    SELECT
        u.name,
        u.email,
        u.department,
        COUNT(r.id) AS registrations,
        DENSE_RANK() OVER (ORDER BY COUNT(r.id) DESC) AS rnk
    FROM users u
    LEFT JOIN registrations r ON r.user_id = u.id
    WHERE u.role = 'user'
    GROUP BY u.id
) ranked
WHERE registrations > 0
ORDER BY rnk, name
LIMIT 15;


-- =====================================================================
-- Q3. Category-level engagement (% share of all registrations)
-- ---------------------------------------------------------------------
-- For every event category, compute the number of events, total
-- registrations, average registrations per event, and the category's
-- share of total registrations.
-- =====================================================================
WITH cat_stats AS (
    SELECT
        e.category,
        COUNT(DISTINCT e.id)  AS events_count,
        COUNT(r.id)           AS registrations
    FROM events e
    LEFT JOIN registrations r ON r.event_id = e.id
    WHERE e.status = 'APPROVED'
    GROUP BY e.category
),
total AS (
    SELECT NULLIF(SUM(registrations), 0) AS total_regs FROM cat_stats
)
SELECT
    cs.category,
    cs.events_count,
    cs.registrations,
    ROUND(cs.registrations::numeric / NULLIF(cs.events_count, 0), 2)
        AS avg_per_event,
    ROUND(100.0 * cs.registrations / t.total_regs, 2)
        AS share_pct
FROM cat_stats cs
CROSS JOIN total t
ORDER BY cs.registrations DESC;


-- =====================================================================
-- Q4. Competition winners (rank=1) per event
-- ---------------------------------------------------------------------
-- Surfaces every recorded gold-medal-equivalent across all competitions,
-- using a ROW_NUMBER window so we can see runner-ups too.
-- =====================================================================
SELECT
    e.name        AS event_name,
    e.category,
    e.date,
    u.name        AS winner,
    u.department,
    res.rank,
    res.prize,
    ROW_NUMBER() OVER (
        PARTITION BY e.id ORDER BY res.rank ASC
    )             AS rank_within_event
FROM results res
JOIN registrations r ON r.id = res.registration_id
JOIN events e        ON e.id = r.event_id
JOIN users u         ON u.id = r.user_id
WHERE e.is_competition = TRUE
ORDER BY e.date DESC, e.name, res.rank ASC;


-- =====================================================================
-- Q5. Monthly registration trend with growth rate
-- ---------------------------------------------------------------------
-- Aggregates registrations by month and uses LAG() to compute the
-- month-over-month percentage change. Useful for the trend chart.
-- =====================================================================
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', r.timestamp)::date AS month_start,
        COUNT(*) AS registrations
    FROM registrations r
    GROUP BY DATE_TRUNC('month', r.timestamp)
)
SELECT
    month_start,
    registrations,
    LAG(registrations) OVER (ORDER BY month_start) AS prev_month,
    CASE
        WHEN LAG(registrations) OVER (ORDER BY month_start) IS NULL
            OR LAG(registrations) OVER (ORDER BY month_start) = 0
        THEN NULL
        ELSE ROUND(
            100.0 * (registrations - LAG(registrations) OVER (ORDER BY month_start))
                  / LAG(registrations) OVER (ORDER BY month_start),
            2
        )
    END AS growth_pct
FROM monthly
ORDER BY month_start;
