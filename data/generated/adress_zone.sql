USE yottaflex_transport;

SELECT
    az.zone_id,
    az.zone_name,
    a.address_id,
    a.approval_status
FROM address_zone AS az
JOIN address AS a
    ON a.zone_id = az.zone_id
WHERE az.approved_status = 'APPROVED'
  AND a.approval_status = 'APPROVED'
ORDER BY az.zone_id, a.address_id
LIMIT 10;