from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st


OUTPUT_COLUMNS = [
    "Test Case ID",
    "Test Case Name",
    "Objective",
    "SQL Query",
    "Expected Result",
]

PROMPT_PATH = Path(__file__).with_name("Customer_Loan_SQL_Generation_Agent_Prompt.md")
SOURCE_FILTER = "BPO_LOAN.PRTFL_TP IN ('IAC','IBC') AND NVL(BPO_LOAN.DEL_IN_SRC_STM_F,0) = 0"


def load_agent_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Make headers tolerant of spaces, underscores, and capitalization."""
    result = frame.copy()
    result.columns = [
        re.sub(r"[^a-z0-9]", "", str(column).lower()) for column in result.columns
    ]
    return result


def value(row: pd.Series, *names: str) -> str:
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if key in row.index and pd.notna(row[key]):
            text = str(row[key]).strip()
            if text and text.lower() not in {"nan", "none"}:
                return text
    return ""


def split_source(source: str) -> tuple[str, str]:
    match = re.match(r"^\s*([\w$#]+)\.([\w$#]+)\s*$", source)
    if not match:
        match = re.search(r"([\w$#]+)\.([\w$#]+)", source)
    if match:
        return match.group(1), match.group(2)
    return "", source.strip()


def source_expression(row: pd.Series) -> str:
    source = value(row, "DirectSourceColumns", "Direct Source Columns", "Direct Source Column(s)")
    logic = value(row, "Logic")
    description = value(row, "DirectSourceDescription", "Direct Source Description")
    logic_lower = logic.lower()

    quoted_value = re.search(r"(['\"]).*?\1", logic)
    if quoted_value and ("constant" in logic_lower or not source):
        return quoted_value.group(0)
    if "automated" in logic_lower and "counter" in logic_lower:
        return "ROW_NUMBER() OVER (ORDER BY NULL)"

    condition_match = re.search(
        r"(?:if|when)\s+([\w$#]+)\s+in\s*\(([^)]+)\)", logic, re.IGNORECASE
    )
    if condition_match and source:
        source_fields = re.findall(r"[A-Za-z][\w$#]*\.[A-Za-z][\w$#]*", source)
        mapped_expression = source_fields[0] if source_fields else source.splitlines()[0].strip()
        values = condition_match.group(2).replace("‘", "'").replace("’", "'")
        return f"CASE WHEN {condition_match.group(1)} IN ({values}) THEN {mapped_expression} END"

    if "concatenate" in logic_lower or "concat" in logic_lower:
        fields = re.findall(r"[A-Za-z][\w$#]*(?:\.[A-Za-z][\w$#]*)?", logic)
        fields = [field for field in fields if field.upper() not in {"CONCATENATE", "CONCAT"}]
        if fields:
            return " || ".join(fields)

    null_match = re.search(r"if\s+([\w$#]+)\s+is\s+null", logic, re.IGNORECASE)
    if null_match and source:
        _, source_column = split_source(source)
        return f"CASE WHEN {null_match.group(1)} IS NOT NULL THEN {source_column} END"

    if source:
        source_fields = re.findall(r"[A-Za-z][\w$#]*\.[A-Za-z][\w$#]*", source)
        return source_fields[0] if source_fields else source.splitlines()[0].strip()
    return "NULL"


def build_sql(rows: pd.DataFrame, tables: pd.DataFrame) -> tuple[str, str, str]:
    first_row = rows.iloc[0]
    target_table = value(first_row, "PhysicalTableName", "Physical Table Name")
    target_columns = [
        value(row, "PhysicalColumnName", "Physical Column Name")
        for _, row in rows.iterrows()
    ]
    source_tables = [
        split_source(value(row, "DirectSourceColumns", "Direct Source Columns", "Direct Source Column(s)"))[0]
        for _, row in rows.iterrows()
    ]
    source_table = next((table for table in source_tables if table), "")
    joins: list[str] = []
    filters: list[str] = []
    for _, table_row in tables.iterrows():
        physical_table = value(table_row, "PhysicalTableName", "Physical Table Name")
        direct_tables = value(table_row, "DirectSourceTables", "Direct Source Table(s)")
        direct_description = value(
            table_row, "DirectSourceDescription", "Direct Source Description"
        )
        if source_table and physical_table and source_table.lower() in direct_tables.lower():
            join_lines = [line.strip() for line in direct_tables.splitlines() if line.strip()]
            if len(join_lines) >= 3 and " join" in join_lines[0].lower():
                first_part = re.split(r"\s+join\s*$", join_lines[0], flags=re.IGNORECASE)[0]
                first_table, first_alias = first_part.rsplit(" ", 1)
                second_table, second_alias = join_lines[1].rsplit(" ", 1)
                condition = join_lines[2].lower().removeprefix("on ")
                joins.append(f"LEFT JOIN {second_table} {second_alias} ON {condition}")
                source_table = f"{first_table} {first_alias}"
        if direct_description:
            filter_text = direct_description.strip()
            if re.search(r"\bis\s+(?:not\s+)?null\b", filter_text, re.IGNORECASE):
                continue
            if filter_text.lower().startswith("where "):
                filters.append(filter_text)
            elif re.search(r"\b(=|<|>|<=|>=|is null|is not null)\b", filter_text, re.IGNORECASE):
                filters.append(f"WHERE {filter_text.replace('FALSE', '0').replace('TRUE', '1')}")

    select_lines = []
    for _, row in rows.iterrows():
        target_column = value(row, "PhysicalColumnName", "Physical Column Name")
        expression = source_expression(row)
        source_match = re.match(r"^(\w+)\s+(\w+)$", source_table)
        if source_match:
            expression = re.sub(
                rf"\b{re.escape(source_match.group(1))}\.",
                f"{source_match.group(2)}.",
                expression,
                flags=re.IGNORECASE,
            )
        select_lines.append(f"    {expression} AS {target_column}")

    sql_lines = ["SELECT"]
    sql_lines.append(",\n".join(select_lines))
    if source_table:
        sql_lines.append(f"FROM {source_table}")
    sql_lines.extend(joins[:2])
    if filters:
        sql_lines.append(filters[0])
    sql_lines[-1] = sql_lines[-1].rstrip(";") + ";"
    return target_table, ", ".join(target_columns), "\n".join(sql_lines)


def generate_cases(workbook: bytes) -> pd.DataFrame:
    sheets = pd.read_excel(io.BytesIO(workbook), sheet_name=None)
    normalized = {name.lower().strip(): normalize_columns(frame) for name, frame in sheets.items()}
    columns = normalized.get("mapping columns")
    tables = normalized.get("mapping tables", pd.DataFrame())
    if any(name.lower().strip() == "mapping tables" for name in sheets):
        raw_tables = pd.read_excel(io.BytesIO(workbook), sheet_name="Mapping Tables", header=None)
        if len(raw_tables) > 2 and raw_tables.shape[1] >= 9:
            tables = pd.DataFrame(
                {
                    "Physical Table Name": raw_tables.iloc[2:, 2],
                    "Direct Source Table(s)": raw_tables.iloc[2:, 7],
                    "Direct Source Description": raw_tables.iloc[2:, 8],
                }
            ).dropna(how="all")
            tables = normalize_columns(tables)
    if columns is None:
        raise ValueError("The workbook must contain a 'Mapping Columns' worksheet.")
    if columns.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    target_table = value(columns.iloc[0], "PhysicalTableName", "Physical Table Name")
    target_columns = [
        value(row, "PhysicalColumnName", "Physical Column Name")
        for _, row in columns.iterrows()
    ]
    target = "TGT"
    source = "BPO_LOAN"
    thaler = "THALER_LOAN"
    primary_key = next((column for column in target_columns if column.endswith("_ID")), target_columns[0])
    mapped = {column.upper(): column for column in target_columns if column}

    def target_column(*candidates: str) -> str:
        return next((mapped[name.upper()] for name in candidates if name.upper() in mapped), primary_key)

    agreement_id = target_column("AR_ID")
    agreement_key = target_column("AR_SUP_KEY")
    event_id = target_column("EV_ID")
    initiating_office = target_column("INITIATING_OFFICE_CODE", "INIT_OFC_CD")
    booking_office = target_column("BOOKING_OFFICE_CODE", "BOOK_OFC_CD")
    insurance_flag = target_column("INSURANCE_COVERAGE_FLAG", "INS_CVRG_F")
    fraud_flag = target_column("FRAUD_FLAG", "FRD_F")
    restructuring_flag = target_column("RESTRUCTURING_FLAG", "RSTC_F")
    target_list = ", ".join(f"{target}.{column}" for column in target_columns if column)
    source_select = ",\n".join(
        f"    {source_expression(row)} AS {value(row, 'PhysicalColumnName', 'Physical Column Name')}"
        for _, row in columns.iterrows()
        if value(row, "PhysicalColumnName", "Physical Column Name")
    )
    base_source = f"FROM STA_CDS_SS_FIN_IN_AR_LOAN_V {source}\nJOIN STA_CDS_SS_THALER_AR_CL_ZID02_V {thaler} ON {source}.DEAL_ID_SRC = {thaler}.NUMCPT\nWHERE {SOURCE_FILTER}"
    target_join = f"FROM {target_table} {target}"
    source_target_join = f"{target}.{agreement_key} = 'FIN_IN|' || {source}.DEAL_ID_SRC"

    query_specs = [
        ("Source-to-target mapping", f"SELECT\n{source_select}\n{base_source};", "Every mapped source expression returns the expected target-compatible value."),
        ("Source and target count reconciliation", f"SELECT (SELECT COUNT(*) FROM STA_CDS_SS_FIN_IN_AR_LOAN_V {source} JOIN STA_CDS_SS_THALER_AR_CL_ZID02_V {thaler} ON {source}.DEAL_ID_SRC = {thaler}.NUMCPT WHERE {SOURCE_FILTER}) AS source_count, (SELECT COUNT(*) {target_join}) AS target_count FROM dual;", "Source and target counts reconcile according to the agreed load policy."),
        ("Duplicate source deal check", f"SELECT {source}.DEAL_ID_SRC, COUNT(*) AS duplicate_count {base_source} GROUP BY {source}.DEAL_ID_SRC HAVING COUNT(*) > 1;", "No duplicate source deal IDs are returned."),
        ("Duplicate target key check", f"SELECT {target}.{primary_key}, COUNT(*) AS duplicate_count {target_join} GROUP BY {target}.{primary_key} HAVING COUNT(*) > 1;", "No duplicate target primary keys are returned."),
        ("Required target columns null check", f"SELECT COUNT(*) AS invalid_rows {target_join} WHERE {target}.{primary_key} IS NULL OR {target}.{agreement_id} IS NULL;", "The invalid row count is zero for required identifiers."),
        ("Join coverage validation", f"SELECT COUNT(*) AS unmatched_rows FROM STA_CDS_SS_FIN_IN_AR_LOAN_V {source} LEFT JOIN STA_CDS_SS_THALER_AR_CL_ZID02_V {thaler} ON {source}.DEAL_ID_SRC = {thaler}.NUMCPT WHERE {SOURCE_FILTER} AND {thaler}.NUMCPT IS NULL;", "No eligible BPO loan is missing its Thaler join partner."),
        ("Agreement lookup validation", f"SELECT COUNT(*) AS invalid_rows {target_join} LEFT JOIN AR_K ON AR_K.AR_ID = {target}.{agreement_id} WHERE {target}.{agreement_key} IS NOT NULL AND AR_K.AR_SUP_KEY <> {target}.{agreement_key};", "Agreement IDs resolve to the expected FIN_IN super key."),
        ("Loan application lookup validation", f"SELECT COUNT(*) AS invalid_rows {target_join} LEFT JOIN EV_K ON EV_K.EV_ID = {target}.{event_id} WHERE {target}.{event_id} IS NOT NULL AND EV_K.EV_SUP_KEY IS NULL;", "Every populated loan application ID resolves in EV_K."),
        ("Initiating office rule", f"SELECT COUNT(*) AS invalid_rows FROM {target_table} {target} JOIN STA_CDS_SS_FIN_IN_AR_LOAN_V {source} ON {source_target_join} WHERE ({source}.PRTFL_TP = 'IAC' AND {target}.{initiating_office} <> '3180') OR ({source}.PRTFL_TP = 'IBC' AND {target}.{initiating_office} <> '4004');", "IAC rows map to 3180 and IBC rows map to 4004."),
        ("Booking office rule", f"SELECT COUNT(*) AS invalid_rows FROM {target_table} {target} JOIN STA_CDS_SS_FIN_IN_AR_LOAN_V {source} ON {source_target_join} WHERE {target}.{booking_office} <> CASE WHEN {source}.OTSND_REPYMT_ST = 8 AND {source}.LOAN_SUBST = 3 AND {source}.FIDUCRE_PRTFL_TP IS NOT NULL AND {source}.FIDUCRE_PRTFL_TP <> 12 THEN '791' ELSE '3180' END;", "Every booking office code follows the specified CASE expression."),
        ("Insurance flag rule", f"SELECT COUNT(*) AS invalid_rows FROM {target_table} {target} JOIN STA_CDS_SS_FIN_IN_AR_LOAN_V {source} ON {source_target_join} WHERE {target}.{insurance_flag} <> CASE WHEN {source}.MKT_PD_TP = '8' THEN 1 ELSE 0 END;", "Insurance coverage is 1 only when MKT_PD_TP equals 8."),
        ("Fraud flag rule", f"SELECT COUNT(*) AS invalid_rows FROM {target_table} {target} JOIN STA_CDS_SS_FIN_IN_AR_LOAN_V {source} ON {source_target_join} WHERE {target}.{fraud_flag} <> CASE WHEN {source}.FRD_FLAG IN ('1','Y') THEN 1 ELSE 0 END;", "Fraud flag values match the source rule."),
        ("Restructuring flag rule", f"SELECT COUNT(*) AS invalid_rows FROM {target_table} {target} JOIN STA_CDS_SS_FIN_IN_AR_LOAN_V {source} ON {source_target_join} WHERE {target}.{restructuring_flag} <> CASE WHEN {source}.RSTC_F = 'Y' THEN 1 ELSE 0 END;", "Restructuring flag values match the source rule."),
        ("Portfolio filter validation", f"SELECT COUNT(*) AS invalid_rows FROM {target_table} {target} JOIN STA_CDS_SS_FIN_IN_AR_LOAN_V {source} ON {target}.{agreement_key} = {source}.DEAL_ID_SRC WHERE {source}.PRTFL_TP NOT IN ('IAC','IBC') OR NVL({source}.DEL_IN_SRC_STM_F,0) <> 0;", "No excluded portfolio or deleted source record reaches the target."),
        ("Agreement super key validation", f"SELECT COUNT(*) AS invalid_rows FROM {target_table} {target} JOIN STA_CDS_SS_FIN_IN_AR_LOAN_V {source} ON {target}.{agreement_key} = {source}.DEAL_ID_SRC WHERE {target}.{agreement_key} <> 'FIN_IN|' || {source}.DEAL_ID_SRC;", "Each agreement super key uses the FIN_IN prefix and source deal ID."),
        ("Generated identifier uniqueness", f"SELECT COUNT(*) AS duplicate_groups FROM {target_table} {target} GROUP BY {target}.{primary_key} HAVING COUNT(*) > 1;", "The generated target identifier is unique."),
        ("Agreement reference integrity", f"SELECT COUNT(*) AS orphan_rows FROM {target_table} {target} LEFT JOIN AR_K ON AR_K.AR_ID = {target}.{agreement_id} WHERE {target}.{agreement_id} IS NOT NULL AND AR_K.AR_ID IS NULL;", "No target agreement reference is orphaned."),
        ("Loan application reference integrity", f"SELECT COUNT(*) AS orphan_rows FROM {target_table} {target} LEFT JOIN EV_K ON EV_K.EV_ID = {target}.{event_id} WHERE {target}.{event_id} IS NOT NULL AND EV_K.EV_ID IS NULL;", "No target loan application reference is orphaned."),
        ("Derived flag domain validation", f"SELECT COUNT(*) AS invalid_rows {target_join} WHERE {target}.{insurance_flag} NOT IN (0,1) OR {target}.{fraud_flag} NOT IN (0,1) OR {target}.{restructuring_flag} NOT IN (0,1);", "All derived flags contain only 0 or 1."),
        ("End-to-end exception count", f"SELECT COUNT(*) AS exception_rows {target_join} WHERE {target}.{primary_key} IS NULL OR {target}.{agreement_id} IS NULL OR {target}.{insurance_flag} NOT IN (0,1);", "The end-to-end UAT exception count is zero."),
    ]
    return pd.DataFrame(
        [
            {"Test Case ID": f"TC-{index:04d}", "Test Case Name": name, "Objective": f"Validate {name.lower()} for {target_table}.", "SQL Query": query, "Expected Result": expected}
            for index, (name, query, expected) in enumerate(query_specs, start=1)
        ],
        columns=OUTPUT_COLUMNS,
    )


def to_excel(cases: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        cases.to_excel(writer, index=False, sheet_name="Test Cases")
    return output.getvalue()


st.set_page_config(page_title="SQL Mapping Agent", page_icon="SQL", layout="wide")
st.title("Functional Specification to Oracle SQL")
st.caption("Upload an Excel functional specification to generate 20 executable UAT queries.")
with st.expander("Agent instructions"):
    st.markdown(load_agent_prompt())

uploaded = st.file_uploader("Functional specification (.xlsx)", type=["xlsx"])
if uploaded:
    try:
        cases = generate_cases(uploaded.getvalue())
        st.success(f"Generated {len(cases)} test case(s).")
        st.dataframe(cases, use_container_width=True, hide_index=True)
        st.download_button(
            "Download testing_query.xlsx",
            data=to_excel(cases),
            file_name="testing_query.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    except Exception as error:
        st.error(f"Could not process the workbook: {error}")
else:
    st.info("Choose an .xlsx file containing the Mapping Columns worksheet to begin.")