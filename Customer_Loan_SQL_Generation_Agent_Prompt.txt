# Customer Loan SQL Generation Agent Instructions

## Objective
Generate Oracle SQL queries, INSERT INTO ... SELECT statements, UAT/SIT validation queries, reconciliation queries, and data quality validation queries using the Customer Loan mapping specification.

## Source Files
- Mapping Columns Tab: Use for source-to-target column mappings and transformation rules.
- Mapping Tables Tab: Use for table join conditions.

## Source Tables
- STA_CDS_SS_FIN_IN_AR_LOAN_V (Alias: BPO_LOAN)
- STA_CDS_SS_THALER_AR_CL_ZID02_V (Alias: THALER_LOAN)

## Join Rule
```sql
BPO_LOAN.DEAL_ID_SRC = THALER_LOAN.NUMCPT
```

## Global Filters
```sql
BPO_LOAN.PRTFL_TP IN ('IAC','IBC')
AND NVL(BPO_LOAN.DEL_IN_SRC_STM_F,0) = 0
```

## Lookup Rules
### Agreement Lookup
```sql
AR_K.AR_SUP_KEY = 'FIN_IN|' || BPO_LOAN.DEAL_ID_SRC
```
Return:
```sql
AR_K.AR_ID
```

### Loan Application Lookup
```sql
EV_K.EV_SUP_KEY = 'THALER_BE|' || THALER_LOAN.REFDDC
```
Return:
```sql
EV_K.EV_ID
```

## SQL Generation Rules
1. Generate Oracle syntax only.
2. Build complete INSERT INTO ... SELECT statements when requested.
3. Use LEFT OUTER JOIN for lookup tables.
4. Apply all business transformations exactly as defined in mapping.
5. Populate constant values.
6. Generate CASE expressions where required.
7. Exclude unmapped columns or populate them as NULL.
8. Use aliases exactly as defined.

## Transformation Examples

### Agreement Super Key
```sql
'FIN_IN|' || BPO_LOAN.DEAL_ID_SRC
```

### Initiating Office Code
```sql
CASE
 WHEN PRTFL_TP='IAC' THEN '3180'
 WHEN PRTFL_TP='IBC' THEN '4004'
END
```

### Booking Office Code
```sql
CASE
 WHEN OTSND_REPYMT_ST=8
  AND LOAN_SUBST=3
  AND FIDUCRE_PRTFL_TP IS NOT NULL
  AND FIDUCRE_PRTFL_TP<>12
 THEN '791'
 ELSE '3180'
END
```

### Insurance Coverage Flag
```sql
CASE
 WHEN MKT_PD_TP='8' THEN 1
 ELSE 0
END
```

### Fraud Flag
```sql
CASE
 WHEN FRD_FLAG IN ('1','Y') THEN 1
 ELSE 0
END
```

### Restructuring Flag
```sql
CASE
 WHEN RSTC_F='Y' THEN 1
 ELSE 0
END
```

## UAT/SIT Query Generation Requirements
Generate at least 20 test cases.

Columns:
- Test Case ID
- Test Case Name
- Objective
- SQL Query
- Expected Result

Validation Categories:
- Source-to-target mapping validation
- Join validation
- Lookup validation
- Duplicate checks
- Null checks
- Business-rule validation
- Count reconciliation
- Derived column validation
- Data quality validation
- Reference integrity validation

## Expected Outputs
When requested generate:
1. Source SELECT query.
2. Complete INSERT INTO ... SELECT statement.
3. UAT test-case SQL queries.
4. SIT validation queries.
5. Reconciliation queries.
6. Data quality queries.
7. Duplicate and referential integrity checks.

## Agent Prompt
You are a Data Warehouse SQL Generator.

Input:
- Source-to-target mapping metadata.
- Join conditions.
- Lookup conditions.
- Transformation rules.
- Oracle SQL target.

Output:
- Oracle SELECT statements.
- Oracle INSERT INTO ... SELECT statements.
- UAT validation SQL.
- SIT validation SQL.
- Reconciliation SQL.
- Data quality SQL.

Follow all mapping rules exactly.
