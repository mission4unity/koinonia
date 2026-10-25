# Koinonia

**Gratis, open-source e-mailnieuwsbrieven voor kerken en christelijke organisaties.**
*Free, open-source email newsletters for churches and Christian non-profits.* — [English below](#english)

*Een project van [Stichting Mission 4 Unity International](https://mission4unity.com).*

Koinonia (Grieks: *gemeenschap*) is een alternatief voor Mailchimp dat je zelf host. Er zijn geen abonnementen, geen limieten op contacten of e-mails en geen reclame in je mails. Je gegevens blijven op je eigen server.

Lees in [docs/EVALUATIE.md](docs/EVALUATIE.md) hoe Koinonia zich verhoudt tot Mailchimp, Brevo, MailerLite, Kit, listmonk, Mautic en kerkspecifieke diensten.

## Wat het kan

- **Contacten en lijsten:** import en export via CSV (ook met Nederlandse kolomnamen), labels, notities en zoeken/filteren. Bulkacties.
- **Aanmeldformulieren:** een openbare pagina en insluitcode zonder scripts of cookies. Dubbele opt-in, interessekeuze (meerdere lijsten in één formulier) en spambescherming zonder CAPTCHA.
- **Campagne-editor met blokken en live voorbeeld:** kop, tekst, afbeelding (upload), knop, scheidingslijn en witruimte. Daarnaast kerkblokken: **Bijbeltekst, gebedspunten, dienst/activiteit met agendabestand, geven/collecte, preek/video (YouTube-plaatje automatisch) en getuigenis**.
- **Echt meertalig:** één campagne met meerdere taalversies; iedereen krijgt automatisch zijn eigen taal. Rechts-naar-links (Arabisch) wordt ondersteund. De beheeromgeving is er in 6 talen (NL, EN, DE, FR, ES, PT); e-mailvoetteksten en publieke pagina's in 14 talen (ook IT, PL, RO, AF, SW, ID, AR, UK).
- **Sjablonen:** gemeentebrief, gebedsbrief, zendingsnieuws, uitnodiging en welkomstmail.
- **Versturen:** testmail, direct of ingepland (met tijdzone), pauzeren/hervatten, tempolimiet en automatisch opnieuw proberen bij storingen. Blijvend onbestelbare adressen worden gemarkeerd.
- **Automatiseringen:** welkomstreeksen met meerdere e-mails en wachttijden.
- **Statistieken:** openingen, kliks per link, afmeldingen, uitsplitsing per taal. Alles is per campagne uit te zetten.
- **Privacy & AVG:** toestemming vastleggen, export per persoon (inzageverzoek), definitief verwijderen, automatisch anonimiseren na een bewaartermijn. Geen externe trackers, lettertypen of scripts.
- **Bezorgbaarheid:** one-click unsubscribe (RFC 8058), een tekstversie bij elke mail en een SPF/DKIM/DMARC-uitleg. Afmeldlinks zijn bestand tegen virusscanners.
- **Team:** onbeperkt gebruikers met de rollen beheerder en redacteur.
- **Openbaar nieuwsbriefarchief** en een donkere modus.

## Snel starten

Je hebt alleen **Python 3.9 of nieuwer** nodig. Op macOS en Linux staat dat er meestal al op. Er hoeft niets geïnstalleerd te worden.

```bash
python3 run.py
```

Open daarna <http://localhost:8080> en volg de installatie (één minuut). Zolang er geen mailserver is ingesteld, worden e-mails als `.eml`-bestand opgeslagen in `data/outbox/`. Zo kun je veilig oefenen.

Opties: `--host 0.0.0.0` (bereikbaar in het netwerk), `--port 8080` en `--db pad/naar/bestand.db`.

### Met Docker

```bash
docker build -t koinonia .
docker run -d -p 8080:8080 -v koinonia-data:/data --name koinonia koinonia
```

## In productie

1. Zet Koinonia op een kleine server (een VPS van een paar euro per maand of een Raspberry Pi is genoeg).
2. Zet er een reverse proxy met HTTPS voor, bijvoorbeeld [Caddy](https://caddyserver.com):
   ```
   nieuwsbrief.jouwkerk.nl {
       reverse_proxy 127.0.0.1:8080
   }
   ```
   Start Koinonia dan met de omgevingsvariabele `KOINONIA_TRUST_PROXY=1`, zodat het echte IP-adres van bezoekers wordt gebruikt voor de spambescherming.
3. Stel bij **Instellingen → Algemeen** het openbare adres in (`https://nieuwsbrief.jouwkerk.nl`) en je postadres.
4. Stel bij **Instellingen → Verzenden** je SMTP-gegevens in en klik op *Opslaan en verbinding testen*.
5. Volg de checklist bij **Instellingen → Bezorgbaarheid** (SPF, DKIM, DMARC).

**Welke mailserver?** Een kleine kerk kan vaak het mailaccount van het eigen domein gebruiken. Voor grotere lijsten zijn er Amazon SES (±$0,10 per 1.000 mails), Brevo (gratis SMTP tot 300 mails per dag) en Mailjet.

**Back-up:** alles staat in één bestand, `data/koinonia.db`, plus de map `data/uploads/`. Kopieer die regelmatig. Gebruik bij een draaiende server bij voorkeur `sqlite3 data/koinonia.db ".backup backup.db"`.

**Let op bij back-ups:** het bestand bevat ook je contactgegevens en het SMTP-wachtwoord (leesbaar opgeslagen). Bewaar back-ups daarom versleuteld of op een afgeschermde plek en deel ze niet.

**Als dienst (systemd):**
```ini
[Unit]
Description=Koinonia
After=network.target

[Service]
WorkingDirectory=/opt/koinonia
ExecStart=/usr/bin/python3 run.py --host 127.0.0.1 --port 8080
Environment=KOINONIA_TRUST_PROXY=1
Restart=always
User=koinonia

[Install]
WantedBy=multi-user.target
```

## Testen

```bash
python3 -m unittest discover -s tests
```

De testsuite bevat unit-tests (opmaak, beveiliging, CSV, vertalingen) en end-to-end-tests. Die doorlopen de hele weg: installatie, import, aanmelden met dubbele opt-in, een campagne in twee talen, verzenden, openingen en kliks, afmelden met één klik, voorkeuren, inplannen, automatiseringen, bounces via een nep-SMTP-server, storingen en anonimisering.

## Vertalen

Vertalingen staan in `koinonia/locales/<taalcode>.json`. Wil je een taal toevoegen?

1. Kopieer `en.json` (voor de volledige beheeromgeving) of alleen de `pub.*`-regels (voor e-mails en publieke pagina's).
2. Vertaal de waarden en laat `{placeholders}` en `{{merge_tags}}` staan.
3. Voeg de code toe aan `UI_LANGS` en/of `LANG_NAMES` in `koinonia/i18n.py`.
4. Draai de tests: die controleren of er niets ontbreekt.

De vertalingen in Swahili, Indonesisch, Afrikaans, Arabisch, Oekraïens, Pools, Roemeens en Italiaans zijn met zorg gemaakt. Laat ze wel nalezen door moedertaalsprekers; verbeteringen zijn van harte welkom.

## Projectstructuur

```
run.py                  start de server en de verzender
koinonia/app.py         WSGI-app: sessies, CSRF, routes, foutpagina's
koinonia/views_*.py     schermen (beheer en publiek)
koinonia/render.py      blokken → e-mail-HTML en platte tekst
koinonia/compose.py     campagne + taal + ontvanger → e-mail
koinonia/worker.py      wachtrij, inplannen, automatiseringen, opschonen
koinonia/audience.py    contacten, lijsten, CSV, toestemming
koinonia/mailer.py      SMTP / bestand
koinonia/locales/       vertalingen
tests/                  unit- en end-to-end-tests
```

## Steun dit werk

Koinonia is en blijft gratis. Het is gemaakt door Stichting Mission 4 Unity International, die zich inzet voor eenheid onder christenen. Gebruikt jouw kerk of organisatie het en wil je het onderhoud en de doorontwikkeling mogelijk maken, dan stellen we een vrijwillige gift van **€60** zeer op prijs. Dat is nooit een voorwaarde om Koinonia te gebruiken. Meer of minder geven mag ook.

Gift: [Stripe (iDEAL, kaart)](https://donate.stripe.com/28EcN57C3bdj4fC3mB9oc0c) · [PayPal](https://www.paypal.com/ncp/payment/PLB-EP65FY59PSBN)

## Licentie

[GNU Affero General Public License v3.0 of later](LICENSE). Je mag Koinonia gratis gebruiken, aanpassen en verspreiden. Bied je een aangepaste versie als dienst aan, dan moet je de broncode ook delen. Zo blijft het voor iedereen vrij.

*„Laat alles bij u in liefde geschieden.” — 1 Korinthe 16:14*

---

<a id="english"></a>
## English

Koinonia (Greek: *fellowship*) is a self-hosted alternative to Mailchimp for churches, missions and Christian non-profits. There are no fees, no contact or email limits and no branding in your emails, and your data stays on your own server.

**Highlights:** a block editor with live preview and church blocks (Bible verse, prayer points, service/event with calendar file, giving, sermon/video, testimony). One campaign can carry several language versions, and each person receives their own language automatically. The admin interface is translated into 6 languages, and email footers and public pages into 14. You also get double opt-in sign-up forms without scripts or CAPTCHAs, automations, scheduling, privacy-first statistics with automatic anonymisation, GDPR tools, RFC 8058 one-click unsubscribe and team roles.

**Run it:** `python3 run.py` (Python 3.9+, no dependencies), then open <http://localhost:8080>. In production, put it behind an HTTPS reverse proxy, set `KOINONIA_TRUST_PROXY=1` and configure SMTP under Settings → Sending.

**Test it:** `python3 -m unittest discover -s tests`

**License:** AGPL-3.0-or-later.

**Support:** Koinonia is free and always will be. It is made by Stichting Mission 4 Unity International. If your church or organisation uses it and you would like to support its upkeep, a voluntary gift of €60 is much appreciated. It is never a condition for using Koinonia.
