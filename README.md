# Vėjo gūsių įspėjimai (Boforto balai)

Kas rytą GitHub Actions paleidžia `vejo_ispejimai.py`, o rezultatai įrašomi į šios
repozitorijos aplanką `output/`. Power Automate iš ten pasiima failus ir išsiunčia laišką.
Jūsų kompiuteris nereikalingas.

Rezultatai:
- `output/vejo_ispejimai.html`: lentelė laiško turiniui
- `output/vejo_zemelapis.png`: žemėlapis (priedas)
- `output/vejo_ispejimai.txt`: tas pats tekstas paprastu formatu

Laikotarpis visada: **šiandien 08:00 – rytoj 13:00** (Vilniaus laiku). Skaičiuojama tik pagal vėjo gūsius.

## 1. Repozitorijos sukūrimas (vieną kartą)
1. github.com → **New repository**, pvz. `vejo-ispejimai`.
   - **Public**: GitHub Actions nemokamas be apribojimų, o Power Automate gali paimti failus be slaptažodžių.
     Matomi bus tik kodas ir orų prognozės įspėjimai.
   - **Private**: Power Automate failų tiesiogiai pasiimti negalės (žr. pabaigą).
2. Įkelkite failus: **Add file → Upload files**:
   - `vejo_ispejimai.py`
   - `requirements.txt`
   - `README.md`
3. Workflow failą reikia įkelti į aplanką `.github/workflows/`:
   **Add file → Create new file**, pavadinime įrašykite `.github/workflows/vejo_ispejimai.yml`
   ir įklijuokite `vejo_ispejimai.yml` turinį → **Commit changes**.
4. Jei turite Open-Meteo komercinį raktą: **Settings → Secrets and variables → Actions →
   New repository secret**, pavadinimas `OPEN_METEO_API_KEY`.

## 2. Pirmas paleidimas
**Actions** → kairėje „Vėjo gūsių įspėjimai“ → **Run workflow**. Po 2–4 min. repozitorijoje
atsiras aplankas `output/` su failais. Atidarykite `vejo_zemelapis.png` ir patikrinkite.

Toliau workflow pasileis pats kas rytą 03:00 UTC (05:00 žiemą / 06:00 vasarą Vilniaus laiku).

## 3. Power Automate srautas
1. **Scheduled cloud flow**, kasdien 06:50, laiko juosta (UTC+02:00) Vilnius.
2. **OneDrive for Business → Upload file from URL** (du kartus):
   - Source URL: `https://raw.githubusercontent.com/<JŪSŲ_VARDAS>/vejo-ispejimai/main/output/vejo_ispejimai.html`
     Destination File Path: `/Orai/vejo_ispejimai.html`, Overwrite: **Yes**
   - Source URL: `.../main/output/vejo_zemelapis.png`
     Destination File Path: `/Orai/vejo_zemelapis.png`, Overwrite: **Yes**
3. **Get file content using path**: `/Orai/vejo_ispejimai.html` (pervadinkite į `HTML`)
   ir `/Orai/vejo_zemelapis.png` (pervadinkite į `Zemelapis`).
4. **Send an email (V2)**: Body (kodo rodinys `</>`) = HTML „File Content“,
   Attachments: `vejo_zemelapis.png` = Zemelapis „File Content“.
5. **Test → Manually.**

## Nustatymai (`vejo_ispejimai.py` viršuje)
| Nustatymas | Reikšmė |
|---|---|
| `MIN_BFT = 8` | nuo kokio gūsių balo įspėti (8 = nuo 17,2 m/s; „virš 8“ → 9) |
| `WINDOW_START_HOUR` / `WINDOW_END_HOUR` | laikotarpis: šiandien 08:00 – rytoj 13:00 |
| `GRID_STEP = 0.5` | tinklelio tankis laipsniais (~40–55 km) |
| `MAX_PLACES_TEXT` / `MAX_LABELS_MAP` | kiek vietų rodyti tekste / žemėlapyje vienam regionui |
| `REGIONS`, `EXTRA_PLACES` | šalys ir miestai, kuriais įvardijamos pavojingos vietos |

Pakeitimus galima daryti tiesiai GitHub'e (atidaryti failą → pieštuko ikona → Commit).

**Open-Meteo:** nemokama versija skirta nekomerciniam naudojimui. Įmonėje reikia mokamo rakto
(open-meteo.com/en/pricing), įrašyto kaip `OPEN_METEO_API_KEY` secret.

## Jei repozitorija turi būti privati
Power Automate negalės parsisiųsti failų per `raw.githubusercontent.com`. Galimi būdai
(abiem reikia IT pagalbos):
- Azure app registracija, kad GitHub Actions įkeltų failus tiesiai į OneDrive/SharePoint per Microsoft Graph;
- arba laiškas siunčiamas tiesiai iš GitHub Actions per įmonės SMTP serverį (be Power Automate).

## Bandymas be interneto
```
python vejo_ispejimai.py --demo
```
