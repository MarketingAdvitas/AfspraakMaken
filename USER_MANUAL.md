# User Manual – AfspraakMaken Azure Functions

## 1) Overview
This project contains Azure HTTP Functions that create reservations/appointments by calling SQL Server stored procedures.

Current functions:

1. **POST `/afspraak`**
   - Calls **`[dbo].[spMaakAfspraak]`** with fixed parameter mapping.
   - Supports advisor list input and returns output/result sets from the procedure.

2. **POST `/reservering`**
   - Calls **`[dbo].[spMaakReservering]`**.
   - Dynamically reads procedure parameters (`sys.parameters`) and matches request fields by name (case-insensitive, special chars ignored).
   - Includes support for keys like `MMJO/funnel`, `datum`, `tijd`, `campaign_id`, `adviseur_id`, `run`.

3. **GET/POST `/availability`**
   - Calls **`[dbo].[psAgendaPicker_GetAvailability]`**.
   - Accepts query parameters and/or JSON body.
   - Dynamically matches request fields to stored procedure parameters.

> Note: In `host.json`, `routePrefix` is set to `""`, so routes are available directly as `/afspraak`, `/reservering`, and `/availability`.

---

## 2) Prerequisites
- Python 3.10+ (recommended 3.11)
- Azure Functions Core Tools v4
- ODBC Driver 18 for SQL Server
- Access to SQL Server database containing:
  - `dbo.spMaakAfspraak`
  - `dbo.spMaakReservering`

Python dependencies (from `requirements.txt`):
- `azure-functions`
- `pyodbc`

---

## 3) Configuration
Use either a full connection string or split SQL settings.

### Option A: Full connection string
- `SQL_CONNECTION_STRING`

### Option B: Split settings
- `SQL_SERVER`
- `SQL_PORT` (default `1433`)
- `SQL_DATABASE_PROD` (used when `run=prod`)
- `SQL_DATABASE_TEST` (used when `run` is anything else)
- `SQL_DATABASE` (optional fallback)
- `SQL_USER`
- `SQL_PASSWORD`
- `SQL_ODBC_DRIVER` (default `ODBC Driver 18 for SQL Server`)
- `SQL_ENCRYPT` (default `yes`)
- `SQL_TRUST_SERVER_CERTIFICATE` (default `no`)
- `SQL_CONNECTION_TIMEOUT` (default `30`)

For local development, copy `local.settings.json.example` to `local.settings.json` and fill in real values.

---

## 4) Local run
From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
func start
```

Default local URL:
- `http://localhost:7071/afspraak`
- `http://localhost:7071/reservering`
- `http://localhost:7071/availability`

---

## 5) Deploy to Azure
## 5.1 Create Azure resources (once)
Create (or reuse):
- Resource Group
- Storage Account
- Function App (Python runtime)

## 5.2 Configure app settings
In Function App configuration, add SQL settings (same names as above).

## 5.3 Publish
From project folder:

```powershell
func azure functionapp publish <YOUR_FUNCTION_APP_NAME>
```

Alternative CI/CD options (GitHub Actions/Azure DevOps) are also possible.

---

## 6) How to call the functions
If your Function App uses Function-level auth, include key:
- Query string: `?code=<FUNCTION_KEY>`
- or header: `x-functions-key: <FUNCTION_KEY>`

### 6.1 Call `/afspraak`
Required fields:
- `klant_id`
- `adviseur_id` (int, array, or CSV string)
- `datum` (`YYYY-MM-DD`)
- `tijd` (`HH:MM` or `HH:MM:SS`)
- `duur_kwartieren`
- `campagne_id`

Example:

```powershell
curl -X POST "https://<your-app>.azurewebsites.net/afspraak?code=<key>" ^
  -H "Content-Type: application/json" ^
  -d "{\"klant_id\":0,\"adviseur_id\":\"18,22,35\",\"datum\":\"2026-06-24\",\"tijd\":\"14:30\",\"duur_kwartieren\":2,\"campagne_id\":77}"
```

### 6.2 Call `/reservering`
Minimum required fields:
- `datum`
- `tijd`
- `duur_kwartieren`
- `campaign_id` (or `campagne_id`)
- `adviseur_id`
- `run`

Required only when `campaign_id`/`campagne_id` = `230`:
- `MMJO/funnel` (or `mmjo_funnel` / `funnel`)

Example:

```powershell
curl -X POST "https://<your-app>.azurewebsites.net/reservering?code=<key>" ^
  -H "Content-Type: application/json" ^
  -d "{\"datum\":\"2026-07-14\",\"tijd\":\"10:30\",\"campaign_id\":123,\"adviseur_id\":[18,22],\"run\":\"A1\",\"MMJO/funnel\":\"web-lead\"}"
```

### 6.3 Call `/availability`
Method:
- `GET` (query string) or `POST` (JSON body)

Stored procedure:
- `[dbo].[psAgendaPicker_GetAvailability]`

Example GET:

```powershell
curl "https://<your-app>.azurewebsites.net/availability?code=<key>&datum=2026-07-14&adviseur_id=18"
```

Example POST:

```powershell
curl -X POST "https://<your-app>.azurewebsites.net/availability?code=<key>" ^
  -H "Content-Type: application/json" ^
  -d "{\"datum\":\"2026-07-14\",\"adviseur_id\":18}"
```

Response includes:
- `result`
- `input`
- `matched_parameters`
- `stored_procedure_output`
- `stored_procedure_result

---

## 7) Troubleshooting
1. **400 Body moet geldige JSON zijn**
   - Request body is not valid JSON.

2. **400 Parameter '...' is verplicht**
   - Required field missing/empty.

3. **500 Database instellingen ontbreken**
   - SQL app settings are incomplete.

4. **500 stored procedure execution error**
   - Check:
     - Function App logs
     - SQL permissions for configured user
     - Stored procedure existence and parameter names/types

5. **Azure page shows only "up and running"**
   - You called root URL instead of function path. Use `/afspraak` or `/reservering`.

---

## 8) Security notes
- Never commit real SQL credentials.
- Store secrets in Azure App Settings / Key Vault.
- Prefer HTTPS-only calls.
- Restrict database user permissions to required procedures.
