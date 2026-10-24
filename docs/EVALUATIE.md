# Evaluatie: Mailchimp, de concurrenten — en wat Koinonia beter doet

*Peildatum: oktober 2026. Prijzen en limieten komen van de officiële prijspagina's en recente vergelijkingen (zie bronnen onderaan). Ze veranderen vaak; controleer ze vóór je een besluit neemt.*

## 1. Het speelveld

| Dienst | Gratis plan | Betaald vanaf | Non-profitkorting | Open source | Echte meertalige campagnes | Data / privacy |
|---|---|---|---|---|---|---|
| **Mailchimp** | 250 contacten, 500 mails/maand (250/dag), eigen logo in mails | $13/mnd | 15% | Nee | Nee (per taal een aparte campagne of segment) | VS; rekent ook afgemelde contacten mee |
| **Brevo** | 300 mails/dag, tot 100.000 contacten, logo in mails | $9/mnd | Beperkt | Nee | Nee | Frankrijk (EU) |
| **MailerLite** | 250 abonnees, 2.500 mails/mnd (ingekrompen juni 2026) | $12/mnd | 30% | Nee | Nee | EU |
| **Kit** (ConvertKit) | 10.000 abonnees, vooral tekstmails | $39/mnd | Nee | Nee | Nee | VS |
| **Constant Contact** | Geen (proefperiode) | $12/mnd | Tot 30% (jaar vooruitbetalen) | Nee | Nee | VS |
| **Mailjet** | 1.000 contacten, 6.000/mnd, max 200/dag | $9/mnd | Nee | Nee | Nee | EU |
| **EmailOctopus** | 2.500 contacten, 10.000/mnd | ±$9/mnd | 20% | Nee | Nee | EU/VS |
| **Flocknote / Text In Church / HeyChurch** | Nee | Tientallen dollars per maand | n.v.t. | Nee | Nee, Engelstalig en VS-gericht | VS |
| **listmonk** | Volledig gratis (zelf hosten) | — | — | Ja (AGPL) | Nee | Eigen server |
| **Mautic** | Volledig gratis (zelf hosten) | — | — | Ja (GPL) | Deels | Eigen server; zeer complex |
| **Keila** | Gratis (zelf hosten) | Cloud betaald | — | Ja (AGPL) | Nee | Eigen server |
| **Sendy** | — | $69 eenmalig | — | Nee | Nee | Eigen server; alleen Amazon SES |

## 2. Wat er mis is met de bestaande oplossingen (voor kerken en christelijke non-profits)

1. **Kosten schalen met je gemeente.** Mailchimp rekent per contact, óók voor afgemelde en niet-bereikbare adressen. Een kerk met 1.500 adressen betaalt al snel honderden euro's per jaar. De non-profitkorting is maar 15%.
2. **Gratis plannen zijn lokkertjes.** 250 contacten (Mailchimp, MailerLite) is minder dan één middelgrote gemeente. Gratis mails hebben altijd het logo van de leverancier.
3. **Meertaligheid ontbreekt.** Migrantenkerken, zendingsorganisaties en internationale werken hebben leden die verschillende talen spreken. Bij alle diensten moet je per taal een aparte campagne bouwen en segmenten onderhouden. Niemand stuurt automatisch de juiste taalversie naar elk contact.
4. **Privacy en AVG.** Veel diensten draaien in de VS, volgen standaard elke opening en klik, en geven je weinig zeggenschap over hoe lang die gegevens bewaard blijven. Voor kerken, die onder de AVG bijzondere persoonsgegevens verwerken (levensbeschouwing!), is dat een reëel risico.
5. **Geen bouwstenen voor de kerk.** Er zijn geen standaardblokken voor een Bijbeltekst, gebedspunten, een dienst of activiteit met "zet in agenda", een collecte- of giftknop, of een preek-/videoblok. Je bouwt alles na met losse tekst en afbeeldingen.
6. **Te complex en te commercieel.** De interfaces zitten vol e-commerce, AI-upsells, advertenties en verkoopfunnels die een vrijwilliger in de kerk niet nodig heeft en die afleiden.
7. **Vendor lock-in.** Exporteren kan, maar automatiseringen, sjablonen en statistieken neem je niet mee.
8. **De open-sourcealternatieven zijn technisch.** listmonk en Mautic vragen Docker, PostgreSQL en serverkennis. listmonk heeft geen automatiseringen. Mautic is overweldigend. Geen van beide is op kerken gericht.
9. **Bezorgbaarheid wordt niet uitgelegd.** Sinds 2024 eisen Gmail en Yahoo SPF, DKIM, DMARC en *one-click unsubscribe* (RFC 8058). Kleine organisaties weten vaak niet wat dat betekent.
10. **Link-scanners schrijven mensen per ongeluk uit.** Bij veel tools schrijft één GET-verzoek op de afmeldlink iemand meteen uit, waardoor virusscanners van bedrijven en scholen leden ongewild afmelden.
11. **Vrijwilligers en rollen.** Op goedkope plannen zit je vaak aan één gebruiker vast, terwijl een kerk met meerdere vrijwilligers werkt.

## 3. Ontwerpkeuzes van Koinonia: op elk punt beter

| # | Probleem | Wat Koinonia doet |
|---|---|---|
| 1, 2 | Kosten, limieten, logo | **Volledig gratis en open source (AGPL-3.0)**. Geen contact- of verzendlimiet, geen reclame of logo in je mails. Je gebruikt je eigen SMTP-dienst (bijv. de mailserver van je eigen domein, Brevo SMTP, Amazon SES of Mailjet). |
| 3 | Meertaligheid | **Eén campagne, meerdere taalversies.** Elk contact krijgt automatisch de versie in zijn eigen taal, met een terugval naar de standaardtaal. Rechts-naar-links talen (Arabisch, Hebreeuws, Farsi) worden goed weergegeven. Beheeromgeving in 6 talen (NL, EN, DE, FR, ES, PT). Afmeld-, voorkeur- en aanmeldpagina's en de mailvoettekst in 14 talen. |
| 4 | Privacy/AVG | **Je data blijft op je eigen server.** Openingen en kliks volgen kan per campagne of helemaal uit. Automatisch wissen van trackinggegevens na een instelbaar aantal dagen. Toestemming wordt per contact vastgelegd (tekst, tijdstip, bron). Gegevensexport per persoon (inzageverzoek) en definitief verwijderen met één klik. Geen externe lettertypen, scripts of trackers in de beheeromgeving. |
| 5 | Kerkblokken | Standaardblokken voor **Bijbeltekst**, **gebedspunten**, **activiteit/dienst met agendabestand (.ics)**, **gift/collecte**, **preek/video** (met YouTube-voorbeeldplaatje), **getuigenis/citaat**, plus koppen, tekst, afbeelding, knop, scheidingslijn en witruimte. Startsjablonen: gemeentebrief, gebedsbrief, zendingsnieuws, uitnodiging en welkomstmail. |
| 6 | Complexiteit | Een rustige, ingetogen interface met alleen wat een kerk nodig heeft. Een voorbeeldweergave die meeloopt terwijl je typt. |
| 7 | Lock-in | Alles staat in één SQLite-bestand. Export van contacten als CSV. Open broncode. |
| 8 | Technische drempel | **Geen afhankelijkheden**: alleen Python 3.9+ (staat standaard op macOS en Linux). Starten met `python3 run.py`. Een Dockerfile ligt klaar voor wie dat wil. |
| 9 | Bezorgbaarheid | Ingebouwde one-click unsubscribe (RFC 8058-headers), een tekstversie naast elke HTML-mail, tempolimiet per minuut en een **checklist voor SPF/DKIM/DMARC** in de instellingen. |
| 10 | Link-scanners | Afmelden via de link vraagt eerst om bevestiging met een knop. Alleen een echte POST (inclusief de one-click van Gmail en Apple) schrijft uit. |
| 11 | Rollen | Onbeperkt aantal gebruikers met de rollen *beheerder* en *redacteur*. |
| — | Extra | Dubbele opt-in per lijst. Formulieren met **interessekeuze** (bijv. "Gebedsbrief" en "Jeugdnieuws" in één formulier). Insluitbare formulieren met spambescherming (honeypot en tijdscontrole) zonder CAPTCHA van derden. Openbaar **nieuwsbriefarchief**. Welkomst- en follow-upreeksen (automatiseringen). Tijdsplanning. Testmail. Persoonlijke velden met terugvalwaarde (`{{first_name|vriend}}`). |

## 4. Eerlijke beperkingen (versie 1)

- Je hebt een **SMTP-verzender** nodig. Koinonia is de software, niet de postbode. Voor kleine kerken volstaat vaak het mailaccount van het eigen domein. Grotere lijsten: Amazon SES (±$0,10 per 1.000 mails) of de gratis SMTP-laag van Brevo of Mailjet.
- **Bounces** worden herkend aan permanente SMTP-fouten bij het verzenden. Het later binnenlezen van bounce-mails (IMAP) en webhooks van providers staat op de roadmap.
- Er is geen SMS of WhatsApp. Dit is bewust: het blijft eenvoudig.
- Hosten moet je zelf doen, of iemand in de gemeente doet het. Een kleine VPS of een Raspberry Pi is genoeg.
- De ingebouwde webserver is bedoeld voor gebruik achter een reverse proxy met HTTPS (Caddy of Nginx). Zie de README.

## 5. Roadmap-ideeën

IMAP-bounceverwerking · A/B-test op onderwerpregel · RSS-naar-mail (preken en blog) · koppelingen met kerkadministratie (LKP, Scipio, ChurchTools, Planning Center) via CSV of API · meer UI-talen via de community (de vertaalbestanden zijn simpele JSON-bestanden).

## Bronnen

- dreamlit.ai: *8 Best Mailchimp Alternatives in 2026* (gevalideerd september 2026)
- fastlancer.org: *Free Mailchimp Alternatives 2026* (augustus 2026)
- brevo.com: *15 Best Email Marketing Platforms 2026*
- mailchimp.com/help: *About the Nonprofit Discount* (15%)
- blog.groupmail.io: *Constant Contact Alternatives for Nonprofits (2026)*
- octeth.com: *Open Source Email Marketing Software: 15 Tools Compared (2026)*
- mailflowauthority.com: *Listmonk Review 2026*
- heychurch.co en flocknote.com: kerkspecifieke diensten
