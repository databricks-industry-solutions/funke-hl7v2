# Recipes by message type

All recipes read a table with the parsed `hl7` column (`parsed_messages` from the bundle, or the table written in SKILL.md Step 4) and run on a SQL warehouse or in a notebook. They expect one message per row: `hl7.MSH[0]`, `hl7.PID[0]` and the message-type filters only see the first message, so split files that hold several messages first (SKILL.md, Split files with several messages). Field positions follow HL7 v2.5.1; check the sending system's interface spec, because feeds often move data between fields or use Z-segments.

## Contents

- ADT: patients and visits
- ORU: lab and vital-sign results
- ORU: results linked to their order (OBR)
- VXU: immunizations
- MDM: clinical document text
- ORM and OML: orders
- SIU: appointments
- Inventory: message types and failed parses

## ADT: patients and visits

```sql
SELECT
  hl7.MSH[0].fields[9][0][2][1]  AS trigger_event,     -- A01 admit, A02 transfer, A03 discharge, A04 register, A08 update
  hl7.EVN[0].fields[2][0][1][1]  AS event_time,        -- EVN-2
  hl7.PID[0].fields[3][0][1][1]  AS patient_id,        -- PID-3.1
  hl7.PID[0].fields[5][0][1][1]  AS family_name,       -- PID-5.1
  hl7.PID[0].fields[5][0][2][1]  AS given_name,        -- PID-5.2
  hl7.PID[0].fields[7][0][1][1]  AS birth_date,        -- PID-7
  hl7.PID[0].fields[8][0][1][1]  AS sex,               -- PID-8
  hl7.PV1[0].fields[2][0][1][1]  AS patient_class,     -- PV1-2 (I inpatient, O outpatient, E emergency)
  hl7.PV1[0].fields[3][0][1][1]  AS unit,              -- PV1-3.1 point of care
  hl7.PV1[0].fields[3][0][3][1]  AS bed,               -- PV1-3.3
  hl7.PV1[0].fields[19][0][1][1] AS visit_number,      -- PV1-19
  hl7.PV1[0].fields[44][0][1][1] AS admit_time,        -- PV1-44
  hl7.PV1[0].fields[45][0][1][1] AS discharge_time     -- PV1-45 (often empty; fall back to EVN-2 for A03)
FROM <table>
WHERE hl7.MSH[0].fields[9][0][1][1] = 'ADT';
```

HL7 timestamps are strings such as `20260106053000`. They can be shorter (`yyyyMMddHHmm`, `yyyyMMddHH`, `yyyyMMdd`), carry fractional seconds and end with a time zone offset (`-0500`). Pad to 14 digits and apply the offset when present; malformed values become NULL instead of failing the query under ANSI mode. Values without an offset are read in the session time zone.

```sql
CASE WHEN <ts> RLIKE '[+-][0-9]{4}$'
  THEN try_to_timestamp(concat(rpad(regexp_extract(<ts>, '^([0-9]{8,14})', 1), 14, '0'), right(<ts>, 5)), 'yyyyMMddHHmmssXX')
  ELSE try_to_timestamp(rpad(regexp_extract(<ts>, '^([0-9]{8,14})', 1), 14, '0'), 'yyyyMMddHHmmss')
END
```

## ORU: lab and vital-sign results

One ORU message carries many OBX segments, and can carry several patients (one PID per patient group). Explode the OBX segments and take the patient from the nearest PID above each result.

```sql
SELECT
  try_element_at(filter(hl7.PID, p -> p.index < obx.index), -1).fields[3][0][1][1] AS patient_id,
  obx.index                     AS segment_index,
  obx.fields[3][0][1][1]        AS observation_code,     -- OBX-3.1 (LOINC when OBX-3.3 = LN)
  obx.fields[3][0][2][1]        AS observation_text,     -- OBX-3.2
  obx.fields[3][0][3][1]        AS coding_system,        -- OBX-3.3
  obx.fields[2][0][1][1]        AS value_type,           -- OBX-2 (NM, ST, TX, CE)
  obx.fields[5][0][1][1]        AS value,                -- OBX-5.1: the whole value for NM, ST and TX
  array_join(transform(array_sort(map_keys(obx.fields[5][0])), c -> obx.fields[5][0][c][1]), '^') AS value_full,  -- all components
  obx.fields[6][0][1][1]        AS units,                -- OBX-6.1
  obx.fields[7][0][1][1]        AS reference_range,      -- OBX-7
  obx.fields[8][0][1][1]        AS abnormal_flag,        -- OBX-8
  obx.fields[11][0][1][1]       AS result_status,        -- OBX-11 (F final, P preliminary, C corrected)
  obx.fields[14][0][1][1]       AS observation_time      -- OBX-14
FROM <table>
LATERAL VIEW explode(hl7.OBX) AS obx
WHERE hl7.MSH[0].fields[9][0][1][1] = 'ORU';
```

Cast `value` with `try_cast(value AS DOUBLE)` only where `value_type = 'NM'`. funke splits OBX-5 on `^`, so for structured numerics (SN, for example `>^10`) `value` holds only the comparator and the number is `obx.fields[5][0][2][1]`; for coded results (CE, CWE) `value` is the code and component 2 the text. `value_full` keeps every component. Repetitions (`~`) beyond the first are in `get(obx.fields[5], 1)` and later (plain `[1]` fails under ANSI mode when there is only one).

## ORU: results linked to their order (OBR)

When a message has several OBR groups, each OBX belongs to the nearest OBR above it. funke keeps segments in line order with their `index`, so take the last OBR whose index is below the OBX's index. This works within one parsed row.

```sql
SELECT path,
  obr.fields[4][0][1][1] AS order_code,        -- OBR-4.1 universal service ID
  obr.fields[7][0][1][1] AS observation_time,  -- OBR-7
  obx.fields[3][0][1][1] AS observation_code,  -- OBX-3.1
  obx.fields[5][0][1][1] AS value              -- OBX-5
FROM (
  SELECT path, obx, try_element_at(filter(hl7.OBR, r -> r.index < obx.index), -1) AS obr
  FROM <table>
  LATERAL VIEW explode(hl7.OBX) AS obx
  WHERE hl7.MSH[0].fields[9][0][1][1] = 'ORU'
);
```

## VXU: immunizations

```sql
SELECT
  hl7.PID[0].fields[3][0][1][1] AS patient_id,
  rxa.fields[3][0][1][1]        AS administered_at,   -- RXA-3
  rxa.fields[5][0][1][1]        AS vaccine_code,      -- RXA-5.1
  rxa.fields[5][0][2][1]        AS vaccine_name,      -- RXA-5.2
  rxa.fields[5][0][3][1]        AS code_system,       -- RXA-5.3 (CVX, NDC)
  rxa.fields[6][0][1][1]        AS dose,              -- RXA-6 (999 means unknown, common for historical doses)
  rxa.fields[7][0][1][1]        AS dose_units,        -- RXA-7
  rxa.fields[9][0][1][1]        AS information_source, -- RXA-9 (00 new administration, 01 historical)
  rxa.fields[20][0][1][1]       AS completion_status,  -- RXA-20 (CP complete, RE refused, NA not administered, PA partial; empty means CP)
  rxa.fields[21][0][1][1]       AS action_code,        -- RXA-21 (A add, U update, D delete)
  orc.fields[3][0][1][1]        AS filler_order,       -- ORC-3.1 record ID
  orc.fields[3][0][2][1]        AS filler_authority,   -- ORC-3.2 assigning system
  hl7.MSH[0].fields[7][0][1][1] AS message_time        -- MSH-7
FROM (
  -- the ORC of this RXA's order group: the nearest ORC above it with no other RXA in between
  SELECT hl7, rxa, if(exists(hl7.RXA, x -> x.index > orc.index AND x.index < rxa.index), NULL, orc) AS orc
  FROM (
    SELECT hl7, rxa, try_element_at(filter(hl7.ORC, c -> c.index < rxa.index), -1) AS orc
    FROM <table>
    LATERAL VIEW explode(hl7.RXA) AS rxa
    WHERE hl7.MSH[0].fields[9][0][1][1] = 'VXU'
  )
);
```

Updates and deletes refer to an earlier record by ORC-3, which is unique together with its assigning system. To count doses actually given: for rows with a non-empty `filler_order`, keep the latest row per `filler_order` and `filler_authority` (by `message_time`) and drop records whose latest `action_code` is `D`; keep rows without ORC-3 as separate doses (common in older feeds); then keep `coalesce(nullif(completion_status, ''), 'CP') IN ('CP', 'PA')`.

## MDM: clinical document text

The note body is spread across OBX-5 values, and a single OBX-5 can repeat (`~`). funke decodes HL7 escapes such as `\.br\` into line breaks, but it also splits OBX-5 on `^` and `&`, so rebuild each repetition from all its components before joining the repetitions and then the segments in order.

```sql
SELECT
  hl7.PID[0].fields[3][0][1][1] AS patient_id,
  hl7.TXA[0].fields[2][0][1][1] AS document_type,   -- TXA-2
  hl7.TXA[0].fields[12][0][1][1] AS document_id,    -- TXA-12
  array_join(
    transform(array_sort(hl7.OBX, (a, b) -> a.index - b.index), o -> array_join(transform(o.fields[5],
      r -> array_join(transform(array_sort(map_keys(r)), c -> array_join(transform(array_sort(map_keys(r[c])), sc -> r[c][sc]), '&')), '^')), '\n')),
    '\n') AS note_text
FROM <table>
WHERE hl7.MSH[0].fields[9][0][1][1] = 'MDM';
```

## ORM and OML: orders

A message can carry several order groups, each an ORC followed by its detail segment (OBR for lab and radiology, RXO for pharmacy). Explode ORC so every order is kept, then attach the OBRs between that ORC and the next one. Orders without an OBR, such as ORC-only cancels and pharmacy orders (the drug is in RXO-1), keep one row with NULL test columns; a message that has OBR but no ORC keeps its OBRs with NULL order columns.

```sql
SELECT
  message_type,
  orc.fields[1][0][1][1] AS order_control,   -- ORC-1 (NW new, CA cancel, XO change)
  orc.fields[2][0][1][1] AS placer_order,    -- ORC-2
  obr.fields[4][0][1][1] AS test_code,       -- OBR-4.1
  obr.fields[4][0][2][1] AS test_name        -- OBR-4.2
FROM (
  SELECT hl7.MSH[0].fields[9][0][1][1] AS message_type, hl7, orc,
    coalesce(get(filter(hl7.ORC, c -> c.index > orc.index), 0).index, 2147483647) AS next_orc
  FROM <table>
  LATERAL VIEW OUTER explode(hl7.ORC) AS orc
  WHERE hl7.MSH[0].fields[9][0][1][1] IN ('ORM', 'OML')
)
LATERAL VIEW OUTER explode(filter(hl7.OBR, r -> r.index > coalesce(orc.index, -1) AND r.index < next_orc)) AS obr;
```

## SIU: appointments

```sql
SELECT
  hl7.MSH[0].fields[9][0][2][1] AS trigger_event,     -- S12 new, S14 modify, S15 cancel
  hl7.SCH[0].fields[1][0][1][1] AS placer_appt_id,    -- SCH-1
  hl7.SCH[0].fields[2][0][1][1] AS filler_appt_id,    -- SCH-2
  hl7.AIP[0].fields[3][0][1][1] AS provider_id,       -- AIP-3.1
  hl7.AIP[0].fields[3][0][2][1] AS provider_family,   -- AIP-3.2
  hl7.AIL[0].fields[3][0][1][1] AS location           -- AIL-3.1
FROM <table>
WHERE hl7.MSH[0].fields[9][0][1][1] = 'SIU';
```

## Inventory: message types and failed parses

Run this first on a new feed.

```sql
SELECT
  coalesce(hl7.MSH[0].fields[9][0][1][1], '(not parsed)') AS message_type,
  hl7.MSH[0].fields[9][0][2][1]                           AS trigger_event,
  hl7.MSH[0].fields[12][0][1][1]                          AS hl7_version,   -- MSH-12
  count(*)                                                AS messages
FROM <table>
GROUP BY ALL
ORDER BY messages DESC;
```
