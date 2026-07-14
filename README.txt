Azure Function: afspraak

Endpoint:
POST /afspraak
(ook /api/afspraak mogelijk als routePrefix niet leeg is)

Verplichte JSON-velden:
- klant_id (int; 0 = nieuwe klant via stored procedure)
- adviseur_id (int, array of ints, of comma-delimited string zoals "18,22,35")
- datum (YYYY-MM-DD, bijv. 2026-06-24)
- tijd (HH:MM of HH:MM:SS, bijv. 14:30)
- duur_kwartieren (int; 1=15 min, 2=30 min, ...)
- campagne_id (int)

Optioneel:
- naam (string)
- email (string)
- productnaam (string)
- afspraak_type (string, default "online")
- opmerkingen (string)
- insteek_id (int)
- prodcat_id (int)
- advcat_id (int)
- vorm_afspraak (string, default "online")
- is_nieuwe_afspraak (bool/0/1, default true)
- create_opportunity_if_missing (bool/0/1, default false)
- overige velden zijn toegestaan en worden teruggegeven in de response onder "input"

Gedrag:
1) De functie doet geen directe INSERT/UPDATE/SELECT meer op tabellen.
2) adviseur_id mag meerdere IDs bevatten; de functie geeft deze als comma-delimited string door aan de SP.
3) De functie roept alleen [dbo].[spMaakAfspraak] aan met alle inputparameters.
4) Output parameters (@klant_id, @campagne_id, @afspraak_id, @campagne_naam, @foutmelding) worden teruggegeven.

Environment variables (aanbevolen, gesplitst):
- SQL_SERVER
- SQL_PORT (optioneel, default 1433)
- SQL_DATABASE
- SQL_USER
- SQL_PASSWORD
- SQL_ODBC_DRIVER (optioneel, default ODBC Driver 18 for SQL Server)
- SQL_ENCRYPT (optioneel, default yes)
- SQL_TRUST_SERVER_CERTIFICATE (optioneel, default no)
- SQL_CONNECTION_TIMEOUT (optioneel, default 30)

Alternatief:
- SQL_CONNECTION_STRING (wordt ook ondersteund)

Voorbeeld request body:
{
  "klant_id": 0,
  "adviseur_id": "18,22,35",
  "datum": "2026-06-24",
  "tijd": "14:30",
  "duur_kwartieren": 2,
  "campagne_id": 77,
  "opmerkingen": "bel klant terug",
  "vorm_afspraak": "online",
  "is_nieuwe_afspraak": true,
  "create_opportunity_if_missing": true
}

Voorbeeld response:
{
  "result": "success",
  "input": { "...": "originele body" },
  "adviseur_id_doorgestuurd": "18,22,35",
  "stored_procedure_output": {
    "klant_id": 1234,
    "campagne_id": 77,
    "afspraak_id": 5678,
    "campagne_naam": "Campagne X",
    "foutmelding": null
  },
  "stored_procedure_result": [
    [
      { "kolom": "waarde" }
    ]
  ]
}


Gebruik in calls: https://afspraken-dmcveachayhxfhaf.westeurope-01.azurewebsites.net/afspraak
Niet de root URL zonder pad, anders krijg je de standaard Azure "up and running" HTML-pagina.

---

Nieuw endpoint:
POST /api/make-reservation (of /make-reservation als routePrefix leeg staat)

Gedrag:
- Roept alleen [dbo].[spMaakReservering] aan.
- Procedure-parameters worden dynamisch gematcht op naam (case-insensitive, special chars genegeerd).
- Ondersteunt aliases zoals campaign_id/campagne_id en MMJO/funnel/mmjo_funnel/funnel.
- Stuurt adviseur_id als comma-delimited string door (bijv. "18,22,35").
- Geeft matched_parameters, output-parameters en resultsets terug.

Verplicht voor dit endpoint:
- datum
- tijd
- campaign_id
- adviseur_id
- run
- MMJO/funnel (of mmjo_funnel / funnel)

Voorbeeld:
POST https://<jouw-host>/api/make-reservation

Availability endpoint (hersteld):
GET/POST /api/availability (of /availability als routePrefix leeg staat)
- Roept [dbo].[psAgendaPicker_GetAvailability] aan.
- Accepteert querystring en/of JSON body.
- Matcht procedure-parameters dynamisch.

Volledige handleiding:
Zie USER_MANUAL.md