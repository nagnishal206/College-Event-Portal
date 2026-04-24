-- =====================================================================
-- analytical_queries.sql
-- College Event Intelligence Portal - Analytical SQL Deliverables
-- ---------------------------------------------------------------------
-- Five complex queries that answer real stakeholder questions. Each uses
-- JOINs, GROUP BY, aggregate functions and subqueries. Comments above
-- every query describe the insight delivered.
-- ---------------------------------------------------------------------
-- NOTE: Step 7 will expand these with additional ranking / window-function
-- variants. The queries below already satisfy the academic requirements
-- and run against the schema defined in models.py.
-- =====================================================================


-- 1. DEPARTMENT WITH HIGHEST PARTICIPATION RATE
--    "Which department's students are most engaged with campus events?"
--    Computes registrations-per-student per department and ranks them.
SELECT
    u.department                                          AS department,
    COUNT(DISTINCT u.id)                                  AS total_students,
    COUNT(r.id)                                           AS total_registrations,
    ROUND(
        COUNT(r.id)::numeric / NULLIF(COUNT(DISTINCT u.id), 0),
        3
    )                                                     AS registrations_per_student
FROM users u
LEFT JOIN registrations r ON r.user_id = u.id
WHERE u.role = 'user'
GROUP BY u.department
ORDER BY registrations_per_student DESC NULLS LAST;


-- 2. TOP 5 MOST POPULAR EVENTS (BY REGISTRATIONS) WITH CREATOR INFO
--    "Which approved events drew the biggest crowds, and who organized them?"
SELECT
    e.id                AS event_id,
    e.name              AS event_name,
    e.category          AS category,
    e.date              AS event_date,
    creator.name        AS organizer,
    creator.department  AS organizer_dept,
    COUNT(r.id)         AS registration_count
FROM events e
JOIN users creator ON creator.id = e.created_by
LEFT JOIN registrations r ON r.event_id = e.id
WHERE e.status = 'APPROVED'
GROUP BY e.id, creator.name, creator.department
ORDER BY registration_count DESC, e.date DESC
LIMIT 5;


-- 3. BUDGET EFFICIENCY PER CATEGORY
--    "How many rupees of budget do we spend per registered participant
--    in each event category? Spotlights cost-effective categories."
SELECT
    e.category                                    AS category,
    COUNT(DISTINCT e.id)                          AS approved_events,
    SUM(e.budget)                                 AS total_budget,
    COUNT(r.id)                                   AS total_registrations,
    ROUND(
        SUM(e.budget) / NULLIF(COUNT(r.id), 0),
        2
    )                                             AS budget_per_participant
FROM events e
LEFT JOIN registrations r ON r.event_id = e.id
WHERE e.status = 'APPROVED'
GROUP BY e.category
ORDER BY budget_per_participant ASC NULLS LAST;


-- 4. COMPETITION WINNERS LEADERBOARD (RANK = 1)
--    "Who won which competition, what prize, and from which department?
--    Uses a subquery to limit to events flagged as competitions."
SELECT
    e.name                AS competition,
    e.date                AS held_on,
    u.name                AS winner,
    u.department          AS winner_department,
    res.prize             AS prize
FROM results res
JOIN registrations r ON r.id = res.registration_id
JOIN users u         ON u.id = r.user_id
JOIN events e        ON e.id = r.event_id
WHERE res.rank = 1
  AND e.id IN (SELECT id FROM events WHERE is_competition = TRUE)
ORDER BY e.date DESC;


-- 5. PROPOSAL APPROVAL FUNNEL BY DEPARTMENT
--    "For each department, what % of proposed events get approved vs
--    rejected vs still pending? Highlights bottlenecks in the pipeline."
WITH dept_status AS (
    SELECT
        creator.department AS department,
        e.status           AS status,
        COUNT(*)           AS cnt
    FROM events e
    JOIN users creator ON creator.id = e.created_by
    GROUP BY creator.department, e.status
)
SELECT
    department,
    SUM(CASE WHEN status = 'APPROVED' THEN cnt ELSE 0 END) AS approved,
    SUM(CASE WHEN status = 'PENDING'  THEN cnt ELSE 0 END) AS pending,
    SUM(CASE WHEN status = 'REJECTED' THEN cnt ELSE 0 END) AS rejected,
    SUM(cnt)                                                AS total_proposed,
    ROUND(
        100.0 * SUM(CASE WHEN status = 'APPROVED' THEN cnt ELSE 0 END)
              / NULLIF(SUM(cnt), 0),
        1
    )                                                       AS approval_rate_pct
FROM dept_status
GROUP BY department
ORDER BY approval_rate_pct DESC NULLS LAST;
