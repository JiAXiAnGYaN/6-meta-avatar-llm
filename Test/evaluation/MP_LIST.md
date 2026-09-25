# German MP List: Source and Validation

The **German MPs** button in Unity and `GET /api/german-members` offer the names of all current members of the German Bundestag for batch generation. This page explains where the list comes from, how the backend builds it, and how it was checked.

## Source

The list comes from the **Stammdaten aller Abgeordneten seit 1949 im XML-Format** (MdB-Stammdaten), the official open data of the German Bundestag:

- Download: <https://www.bundestag.de/resource/blob/472878/MdB-Stammdaten.zip>
- Overview page: <https://www.bundestag.de/services/opendata>
- Publisher: Deutscher Bundestag, Verwaltung. The data is updated by the Bundestag whenever members join or leave.
- Content: one `MDB` record for every member since 1949 with an ID, all name variants over time, biography, party, and one `WAHLPERIODE` entry per electoral period with the mandate dates, constituency and parliamentary group.

We use this source instead of Wikipedia or a hand-written list because it is:

- **authoritative**: published by the Bundestag itself;
- **complete and structured**: first name, nobility particle, prefix and surname are separate fields, so names are built the same way every time;
- **current without manual work**: members who leave get an end date (`MDBWP_BIS`) and their successors are added, and the backend downloads the file again every six hours.

## How the backend builds the list

`german_mps()` and `_read_mps()` in `backend_python/main.py`:

1. Download the ZIP (at most once every six hours) and read the XML file inside.
2. Keep every member who has a `WAHLPERIODE` with `WP = 21` (the current electoral period, set by `META_AVATAR_BUNDESTAG_PERIOD`) and **no end date** `MDBWP_BIS`. Members who left during the period are dropped.
3. Take the member's current name (the `NAME` entry without `HISTORIE_BIS`) and join `VORNAME ADEL PRAEFIX NACHNAME`. Academic titles (`Dr.`, `Prof.`) and the place suffix (`ORTSZUSATZ`, for example "(Peine)") are left out, because they are not part of how the person is usually named.
4. Keep only plausible person names (letters, spaces, hyphens, apostrophes, dots), remove duplicates and sort alphabetically.

## Validation

`validate_mp_list.py` reads the same official file independently, rebuilds the list with all details, and compares it with what the running backend returns. It also writes every member of the period with ID, name parts, party, parliamentary group and mandate dates to `mp_list_official.csv`.

```bash
cd Test/evaluation
python validate_mp_list.py               # backend must be running on port 8000
python validate_mp_list.py --no-backend  # only analyse the official data
```

### Result (data version of 29 April 2026, checked on 25 September 2026)

| Check | Result |
| --- | --- |
| People with a mandate in period 21 | 635 |
| Left during the period, correctly excluded | 5 (Annalena Baerbock, Robert Habeck, Henning Otte, Carsten Träger, Uwe Foullong) |
| Current members | **630**, the legal size of the 21st Bundestag |
| Names returned by the backend | 630 |
| In the official data but missing in the backend | 0 |
| Returned by the backend but not in the official data | 0 |
| Different members with the same displayed name | 0 |
| Names wrongly rejected by the name filter | 0 |

**The backend list is identical to the official list of current members.**

Current members by parliamentary group: CDU/CSU 208, AfD 150, SPD 120, Bündnis 90/Die Grünen 85, Die Linke 64, without group 3. Mandates: 275 direct, 355 via state list.

### Names that need special handling

| Case | Count | Example | Handled |
| --- | --- | --- | --- |
| Umlauts and other non-ASCII letters | 114 | Norbert Röttgen, Julia Klöckner | yes |
| Hyphenated names | 28 | Katrin Göring-Eckardt | yes |
| Prefix such as von, van, de, dos | 8 | Beatrix von Storch, Jan van Aken, Catarina dos Santos-Wintz | yes |
| Place suffix | 7 | Hubertus Heil (Peine), Carsten Müller (Braunschweig) | dropped; no two current members share a name, so nothing is merged |
| Academic title | 105 | Dr. Gregor Gysi | dropped |
| Name changed during the career | 16 | Katrin Göring-Eckardt, Dorothee Bär | the current name is used |

### Findings

1. **Full given names instead of the usual name.** For 15 members the `VORNAME` field holds all given names, for example `Johann David Wadephul`, who is usually called Johann Wadephul. The GPT route draws a person from the name alone, so the less familiar full name may give a weaker likeness. A list of preferred first names, or using only the first given name for the prompt, would avoid this.
2. **Abbreviated title of nobility.** The one `ADEL` value is abbreviated: `Christian Frhr. von Stetten` instead of *Christian Freiherr von Stetten*. Writing out `Frhr.` as `Freiherr` would make the name read naturally.

Neither finding affects the completeness of the list.
