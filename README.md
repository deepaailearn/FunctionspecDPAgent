# SQL Mapping Agent

This local Streamlit agent reads the Markdown agent prompt and a functional specification workbook. It creates `testing_query.xlsx` with 20 UAT/SIT queries in these columns:

`Test Case ID`, `Test Case Name`, `Objective`, `SQL Query`, `Expected Result`

## Run

```text
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The workbook should contain a `Mapping Columns` worksheet and, when joins or filters are needed, a `Mapping Tables` worksheet. The SQL rules are based on `SQL_Mapping_Agent_Guide.txt`.

The generated cases cover source-to-target mapping, joins, lookups, duplicates, nulls, business rules, count reconciliation, derived flags, data quality, and referential integrity. Queries are read-only Oracle SQL and use the rules in `Customer_Loan_SQL_Generation_Agent_Prompt.md`.

After uploading a workbook, use the built-in question field to ask multiple questions about the generated cases. Each question and answer remains visible until you select **Clear conversation**. You can request a particular SQL query with questions such as `How many queries?`, `Show TC-0007`, `Generate the duplicate SQL query`, `Generate the null check SQL`, and `What is the expected result for TC-0011?`.

You can also request a new mapped query at runtime by naming workbook columns, for example `Generate a new query for AR_ID and AR_SUP_KEY` or `Generate a query for Loan Application Event ID`. The app returns a read-only Oracle `SELECT` using the uploaded mapping, joins, transformations, and filters.