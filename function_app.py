import json
import logging
import os
import re
from datetime import date, time

import azure.functions as func
import pyodbc

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


class ValidationError(Exception):
    pass


def _require(value, name):
    if value is None:
        raise ValidationError(f"Parameter '{name}' is verplicht.")
    return value


def _parse_adviseur_ids(raw_value) -> list[int]:
    try:
        if isinstance(raw_value, int):
            ids = [raw_value]
        elif isinstance(raw_value, list):
            ids = []
            for item in raw_value:
                item_str = str(item).strip()
                if item_str:
                    ids.append(int(item_str))
        else:
            value = str(raw_value).strip()
            ids = [int(item.strip()) for item in value.split(",") if item.strip()]
    except (TypeError, ValueError) as ex:
        raise ValidationError("'adviseur_id' moet een lijst met numerieke ids zijn.") from ex

    if not ids:
        raise ValidationError("'adviseur_id' moet minimaal 1 id bevatten.")

    return ids


def _optional_int(value, name):
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as ex:
        raise ValidationError(f"Parameter '{name}' moet een getal zijn.") from ex


def _parse_bool(value, name, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0

    text = str(value).strip().lower()
    if text in {"1", "true", "ja", "yes"}:
        return True
    if text in {"0", "false", "nee", "no"}:
        return False

    raise ValidationError(f"Parameter '{name}' moet true/false of 1/0 zijn.")


def _parse_payload(payload: dict) -> dict:
    afspraak_datum_raw = _require(payload.get("datum"), "datum")
    afspraak_tijd_raw = _require(payload.get("tijd"), "tijd")
    duur_kwartieren = int(_require(payload.get("duur_kwartieren"), "duur_kwartieren"))
    adviseur_ids = _parse_adviseur_ids(_require(payload.get("adviseur_id"), "adviseur_id"))
    klant_id = int(_require(payload.get("klant_id"), "klant_id"))
    campagne_id = int(_require(payload.get("campagne_id"), "campagne_id"))

    if duur_kwartieren < 1:
        raise ValidationError("'duur_kwartieren' moet minimaal 1 zijn.")

    try:
        afspraak_datum = date.fromisoformat(str(afspraak_datum_raw))
    except ValueError as ex:
        raise ValidationError("'datum' moet formaat YYYY-MM-DD hebben, bijvoorbeeld 2026-06-24.") from ex

    try:
        afspraak_tijd = time.fromisoformat(str(afspraak_tijd_raw))
    except ValueError as ex:
        raise ValidationError("'tijd' moet formaat HH:MM of HH:MM:SS hebben, bijvoorbeeld 14:30.") from ex

    afspraak_type = str(payload.get("afspraak_type", "")).strip().lower()
    derived_is_nieuwe = True if afspraak_type == "nieuw" else False if afspraak_type == "bestaand" else True

    return {
        "klant_id": klant_id,
        "adviseur_ids": adviseur_ids,
        "datum": afspraak_datum,
        "tijd": afspraak_tijd,
        "duur_kwartieren": duur_kwartieren,
        "campagne_id": campagne_id,
        "naam": payload.get("naam"),
        "email": payload.get("email"),
        "productnaam": payload.get("productnaam"),
        "afspraak_type": payload.get("afspraak_type", "online"),
        "opmerkingen": payload.get("opmerkingen"),
        "insteek_id": _optional_int(payload.get("insteek_id"), "insteek_id"),
        "prodcat_id": _optional_int(payload.get("prodcat_id"), "prodcat_id"),
        "advcat_id": _optional_int(payload.get("advcat_id"), "advcat_id"),
        "vorm_afspraak": payload.get("vorm_afspraak", "online"),
        "is_nieuwe_afspraak": _parse_bool(payload.get("is_nieuwe_afspraak"), "is_nieuwe_afspraak", derived_is_nieuwe),
        "create_opportunity_if_missing": _parse_bool(
            payload.get("create_opportunity_if_missing"), "create_opportunity_if_missing", False
        ),
    }


def _build_connection_string_from_parts() -> str:
    driver = os.getenv("SQL_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    server = os.getenv("SQL_SERVER")
    port = os.getenv("SQL_PORT", "1433")
    database = os.getenv("SQL_DATABASE")
    user = os.getenv("SQL_USER")
    password = os.getenv("SQL_PASSWORD")
    encrypt = os.getenv("SQL_ENCRYPT", "yes")
    trust_server_certificate = os.getenv("SQL_TRUST_SERVER_CERTIFICATE", "no")
    timeout = os.getenv("SQL_CONNECTION_TIMEOUT", "30")

    missing = [
        name
        for name, value in {
            "SQL_SERVER": server,
            "SQL_DATABASE": database,
            "SQL_USER": user,
            "SQL_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Database instellingen ontbreken. Zet SQL_CONNECTION_STRING of deze variabelen: "
            + ", ".join(missing)
        )

    return (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},{port};"
        f"Database={database};"
        f"Uid={user};"
        f"Pwd={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_server_certificate};"
        f"Connection Timeout={timeout};"
    )


def _get_connection() -> pyodbc.Connection:
    conn_str = os.getenv("SQL_CONNECTION_STRING")
    if not conn_str:
        conn_str = _build_connection_string_from_parts()
    return pyodbc.connect(conn_str)


def _read_all_result_sets(cursor) -> list[list[dict]]:
    result_sets = []
    while True:
        if cursor.description:
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result_sets.append(
                [
                    {columns[idx]: row[idx] for idx in range(len(columns))}
                    for row in rows
                ]
            )

        if not cursor.nextset():
            break

    return result_sets


def _call_sp_maak_afspraak(cursor, data: dict) -> dict:
    adviseur_csv = ",".join(str(item) for item in data["adviseur_ids"])
    cursor.execute(
        """
        DECLARE @klant_id INT = ?;
        DECLARE @campagne_id INT = ?;
        DECLARE @afspraak_id INT;
        DECLARE @campagne_naam NVARCHAR(255);
        DECLARE @foutmelding NVARCHAR(500);

        EXEC [dbo].[spMaakAfspraak]
            @klant_id = @klant_id OUTPUT,
            @campagne_id = @campagne_id OUTPUT,
            @adviseur_id = ?,
            @datum = ?,
            @tijd = ?,
            @duur_kwartieren = ?,
            @naam = ?,
            @email = ?,
            @productnaam = ?,
            @afspraak_type = ?,
            @opmerkingen = ?,
            @insteek_id = ?,
            @prodcat_id = ?,
            @advcat_id = ?,
            @vorm_afspraak = ?,
            @is_nieuwe_afspraak = ?,
            @create_opportunity_if_missing = ?,
            @afspraak_id = @afspraak_id OUTPUT,
            @campagne_naam = @campagne_naam OUTPUT,
            @foutmelding = @foutmelding OUTPUT;

        SELECT
            @klant_id AS klant_id,
            @campagne_id AS campagne_id,
            @afspraak_id AS afspraak_id,
            @campagne_naam AS campagne_naam,
            @foutmelding AS foutmelding;
        """,
        data["klant_id"],
        data["campagne_id"],
        adviseur_csv,
        data["datum"],
        data["tijd"],
        data["duur_kwartieren"],
        data["naam"],
        data["email"],
        data["productnaam"],
        data["afspraak_type"],
        data["opmerkingen"],
        data["insteek_id"],
        data["prodcat_id"],
        data["advcat_id"],
        data["vorm_afspraak"],
        int(data["is_nieuwe_afspraak"]),
        int(data["create_opportunity_if_missing"]),
    )

    result_sets = _read_all_result_sets(cursor)
    output = {}
    if result_sets and result_sets[-1]:
        row = result_sets[-1][0]
        expected = {"klant_id", "campagne_id", "afspraak_id", "campagne_naam", "foutmelding"}
        if expected.issubset(set(row.keys())):
            output = {
                "klant_id": row.get("klant_id"),
                "campagne_id": row.get("campagne_id"),
                "afspraak_id": row.get("afspraak_id"),
                "campagne_naam": row.get("campagne_naam"),
                "foutmelding": row.get("foutmelding"),
            }
            result_sets = result_sets[:-1]

    return {
        "output": output,
        "result_sets": result_sets,
        "adviseur_id_doorgestuurd": adviseur_csv,
    }


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower().lstrip("@"))


def _prepare_make_reservation_payload(payload: dict) -> dict:
    prepared = dict(payload)

    if "adviseur_id" in prepared and prepared["adviseur_id"] is not None:
        adviseur_ids = _parse_adviseur_ids(prepared["adviseur_id"])
        prepared["adviseur_id"] = ",".join(str(item) for item in adviseur_ids)

    if "MMJO/funnel" in prepared and "mmjo_funnel" not in prepared:
        prepared["mmjo_funnel"] = prepared["MMJO/funnel"]

    return prepared


def _build_value_lookup(payload: dict) -> dict:
    lookup = {}
    for key, value in payload.items():
        lookup[_normalize_name(key)] = value

    aliases = (
        ("campaignid", "campagneid"),
        ("adviseurid", "advisorid"),
    )
    for left, right in aliases:
        if left in lookup and right not in lookup:
            lookup[right] = lookup[left]
        elif right in lookup and left not in lookup:
            lookup[left] = lookup[right]

    return lookup


def _declare_sql_type(sql_type: str, max_length: int, precision: int, scale: int) -> str:
    type_name = str(sql_type).lower()

    if type_name in {"nvarchar", "nchar"}:
        length = "MAX" if max_length == -1 else str(max(1, int(max_length / 2)))
        return f"{sql_type}({length})"

    if type_name in {"varchar", "char", "varbinary", "binary"}:
        length = "MAX" if max_length == -1 else str(max(1, int(max_length)))
        return f"{sql_type}({length})"

    if type_name in {"decimal", "numeric"}:
        return f"{sql_type}({precision},{scale})"

    if type_name in {"datetime2", "datetimeoffset", "time"}:
        return f"{sql_type}({scale})"

    return str(sql_type)


def _get_sp_parameters(cursor, schema_name: str, procedure_name: str) -> list[dict]:
    cursor.execute(
        """
        SELECT
            p.name AS parameter_name,
            TYPE_NAME(p.user_type_id) AS sql_type,
            p.max_length,
            p.precision,
            p.scale,
            p.is_output
        FROM sys.parameters p
        INNER JOIN sys.procedures sp ON sp.object_id = p.object_id
        INNER JOIN sys.schemas s ON s.schema_id = sp.schema_id
        WHERE s.name = ? AND sp.name = ?
        ORDER BY p.parameter_id
        """,
        schema_name,
        procedure_name,
    )

    rows = cursor.fetchall()
    if not rows:
        raise RuntimeError(f"Stored procedure [{schema_name}].[{procedure_name}] heeft geen parameters of bestaat niet.")

    return [
        {
            "name": row[0],
            "sql_type": row[1],
            "max_length": row[2],
            "precision": row[3],
            "scale": row[4],
            "is_output": bool(row[5]),
        }
        for row in rows
    ]


def _to_sql_value(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _call_sp_dynamic(cursor, schema_name: str, procedure_name: str, payload: dict) -> dict:
    parameters = _get_sp_parameters(cursor, schema_name, procedure_name)
    values = _build_value_lookup(payload)

    sql_args = []
    declare_lines = []
    exec_lines = []
    output_selects = []
    matched_parameters = []

    for parameter in parameters:
        parameter_name = str(parameter["name"]).lstrip("@")
        normalized_name = _normalize_name(parameter_name)
        has_value = normalized_name in values
        is_output = bool(parameter["is_output"])

        if is_output:
            variable_name = "@out_" + re.sub(r"[^A-Za-z0-9_]", "_", parameter_name)
            declaration_type = _declare_sql_type(
                parameter["sql_type"], parameter["max_length"], parameter["precision"], parameter["scale"]
            )

            if has_value:
                declare_lines.append(f"DECLARE {variable_name} {declaration_type} = ?;")
                sql_args.append(_to_sql_value(values[normalized_name]))
            else:
                declare_lines.append(f"DECLARE {variable_name} {declaration_type};")

            exec_lines.append(f"    @{parameter_name} = {variable_name} OUTPUT")
            output_selects.append(f"{variable_name} AS [{parameter_name}]")
            matched_parameters.append(parameter_name)
            continue

        if has_value:
            exec_lines.append(f"    @{parameter_name} = ?")
            sql_args.append(_to_sql_value(values[normalized_name]))
            matched_parameters.append(parameter_name)

    if not exec_lines:
        raise ValidationError("Geen procedure-parameters konden worden gematcht met de request body.")

    sql_text_parts = []
    if declare_lines:
        sql_text_parts.extend(declare_lines)

    sql_text_parts.append(f"EXEC [{schema_name}].[{procedure_name}]")
    sql_text_parts.append(",\n".join(exec_lines) + ";")

    if output_selects:
        sql_text_parts.append("SELECT " + ", ".join(output_selects) + ";")

    cursor.execute("\n".join(sql_text_parts), *sql_args)

    result_sets = _read_all_result_sets(cursor)
    output = {}
    if output_selects and result_sets and result_sets[-1]:
        output = result_sets[-1][0]
        result_sets = result_sets[:-1]

    return {
        "output": output,
        "result_sets": result_sets,
        "matched_parameters": matched_parameters,
    }


def _validate_make_reservation_payload(payload: dict):
    required_fields = ["datum", "tijd", "campaign_id", "adviseur_id", "run"]

    for field in required_fields:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValidationError(f"Parameter '{field}' is verplicht.")

    funnel_value = payload.get("MMJO/funnel")
    if funnel_value is None:
        funnel_value = payload.get("mmjo_funnel", payload.get("funnel"))

    if funnel_value is None or (isinstance(funnel_value, str) and not funnel_value.strip()):
        raise ValidationError("Parameter 'MMJO/funnel' (of 'mmjo_funnel'/'funnel') is verplicht.")


@app.route(route="make-reservation", methods=["POST"])
def make_reservation(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Make-reservation API aangeroepen")

    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Body moet geldige JSON zijn."}),
            status_code=400,
            mimetype="application/json",
        )

    if not isinstance(payload, dict):
        return func.HttpResponse(
            json.dumps({"error": "Body moet een JSON object zijn."}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        _validate_make_reservation_payload(payload)
        prepared_payload = _prepare_make_reservation_payload(payload)
    except (ValidationError, ValueError) as ex:
        return func.HttpResponse(
            json.dumps({"error": str(ex)}),
            status_code=400,
            mimetype="application/json",
        )

    conn = None
    cursor = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        sp_result = _call_sp_dynamic(cursor, "dbo", "spMaakReservering", prepared_payload)
        conn.commit()

        return func.HttpResponse(
            json.dumps(
                {
                    "result": "success",
                    "input": payload,
                    "matched_parameters": sp_result["matched_parameters"],
                    "stored_procedure_output": sp_result["output"],
                    "stored_procedure_result": sp_result["result_sets"],
                },
                default=str,
            ),
            status_code=200,
            mimetype="application/json",
        )
    except RuntimeError as ex:
        return func.HttpResponse(
            json.dumps({"error": str(ex)}),
            status_code=500,
            mimetype="application/json",
        )
    except Exception:
        logging.exception("Fout bij aanroepen van spMaakReservering")
        if conn:
            conn.rollback()
        return func.HttpResponse(
            json.dumps({"error": "Interne fout bij uitvoeren van stored procedure."}),
            status_code=500,
            mimetype="application/json",
        )
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route(route="afspraak", methods=["POST"])
def afspraak(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Afspraak API aangeroepen")

    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Body moet geldige JSON zijn."}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        data = _parse_payload(payload)
    except (ValidationError, ValueError) as ex:
        return func.HttpResponse(
            json.dumps({"error": str(ex)}),
            status_code=400,
            mimetype="application/json",
        )

    conn = None
    cursor = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        sp_result = _call_sp_maak_afspraak(cursor, data)
        conn.commit()

        return func.HttpResponse(
            json.dumps(
                {
                    "result": "success",
                    "input": payload,
                    "campaign_id": sp_result["output"].get("campagne_id", data["campagne_id"]),
                    "klant_id": sp_result["output"].get("klant_id", data["klant_id"]),
                    "adviseur_id_doorgestuurd": sp_result["adviseur_id_doorgestuurd"],
                    "stored_procedure_output": sp_result["output"],
                    "stored_procedure_result": sp_result["result_sets"],
                },
                default=str,
            ),
            status_code=200,
            mimetype="application/json",
        )
    except RuntimeError as ex:
        return func.HttpResponse(
            json.dumps({"error": str(ex)}),
            status_code=500,
            mimetype="application/json",
        )
    except Exception:
        logging.exception("Fout bij aanroepen stored procedure")
        if conn:
            conn.rollback()
        return func.HttpResponse(
            json.dumps({"error": "Interne fout bij uitvoeren van stored procedure."}),
            status_code=500,
            mimetype="application/json",
        )
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()