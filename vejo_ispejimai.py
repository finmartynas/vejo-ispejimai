#!/usr/bin/env python3
"""
Vėjo gūsių (Boforto) įspėjimų generatorius.

Kas daroma:
  1. Kiekvienas regionas (Anglija, Škotija, Velsas, Airija, Ispanija, Prancūzija,
     Vokietija, Nyderlandai, Belgija, Liuksemburgas, Šveicarija, Austrija,
     Italija) padengiamas tankiu taškų tinkleliu
     (numatyta kas 0,5°, apie 40–55 km), pridedami ir pavadinti miestai / uostai.
  2. Iš Open-Meteo API paimama valandinė vėjo GŪSIŲ prognozė (m/s).
  3. m/s perskaičiuojami į Boforto balus.
  4. Laikotarpis visada: šiandien 08:00 – rytoj 13:00 (LT laiku).
  5. Kiekvienam regionui randami laikotarpiai „nuo – iki“, kai gūsiai >= MIN_BFT,
     ir konkrečios vietos (artimiausias miestas prie kiekvieno pavojingo langelio).
  6. Išsaugoma:
       output/vejo_ispejimai.txt   - tekstas laiškui
       output/vejo_ispejimai.html  - lentelė laiško turiniui (Power Automate)
       output/vejo_laiskas.json    - paruoštas laiškas su žemėlapiu tekste (Power Automate)
       output/vejo_zemelapis.png   - žemėlapis: nuspalvintos zonos, kur gūsiai >= MIN_BFT,
                                     ir užrašyti artimiausi miestai

Paleidimas:
    python vejo_ispejimai.py                    # šiandien 08:00 – rytoj 13:00
    python vejo_ispejimai.py --date 2026-11-16  # kitai datai
    python vejo_ispejimai.py --lang en          # tekstas angliškai
    python vejo_ispejimai.py --demo             # bandomieji duomenys be orų API

Reikia: pip install requests pandas numpy matplotlib
"""

import argparse
import datetime as dt
import base64
import html
import json
import math
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402
from matplotlib.patches import Polygon, Patch, Rectangle  # noqa: E402

# =====================================================================
# NUSTATYMAI — keiskite čia
# =====================================================================
MIN_BFT = 8                 # įspėjimas, kai gūsiai >= šio balo (8 Bft = nuo 17,2 m/s)
WINDOW_START_HOUR = 8       # ataskaitos pradžia: šiandien 08:00
WINDOW_END_HOUR = 13        # ataskaitos pabaiga: rytoj 13:00
FRIDAY_UNTIL_MONDAY = True  # penktadienį: nuo penktadienio 08:00 iki pirmadienio 13:00
FORECAST_DAYS = 5           # kiek dienų parsisiųsti (5 = užtenka ir penktadienio ataskaitai)
TIMEZONE = "Europe/Vilnius" # kokiu laiku rodyti valandas
TZ_LABEL = {"lt": "LT laiku", "en": "Lithuanian time"}
GRID_STEP = 0.5             # tinklelio žingsnis laipsniais (0.25 = tiksliau, bet 4x daugiau taškų)
MERGE_GAP_HOURS = 2         # pertraukas iki tiek valandų sujungti į vieną laikotarpį
MAX_PLACES_TEXT = 6         # kiek vietų išvardinti tekste vienam laikotarpiui
MAX_LABELS_MAP = 2          # kiek vietų užrašyti žemėlapyje vienam regionui
MODEL = "icon_seamless"     # arba pvz. "ecmwf_ifs025", "icon_seamless", "ukmo_seamless"
API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")  # komercinis raktas (jei turite)
# Kur saugoti rezultatus. GitHub Actions naudoja aplanką "output" šalia skripto.
OUTPUT_DIR = Path(os.environ.get("VEJO_OUTPUT_DIR",
                                 Path(__file__).resolve().parent / "output"))

# Laiškas su žemėlapiu tekste (per Power Automate „Send an HTTP request“).
# Gavėjus įrašykite čia; jei sąrašas tuščias, vejo_laiskas.json nekuriamas.
EMAIL_TO = [
    # "logistika@imone.lt",
]
EMAIL_BCC = []              # pvz. vairuotojų adresai, kad nesimatytų vieni kitiems
EMAIL_SUBJECT = {"lt": "Vėjo gūsių įspėjimai", "en": "Wind gust warnings"}

MAP_EXTENT = (-15.5, 19.5, 35.5, 59.8)  # ilguma min, max, platuma min, max

GEOJSON_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_50m_admin_0_map_units.geojson")
GEOJSON_CACHE = Path(__file__).resolve().parent / "ne_50m_admin_0_map_units.geojson"

# Boforto skalės ribos m/s (balo apatinė riba): 1 Bft nuo 0,3 ... 12 Bft nuo 32,7
BFT_LIMITS = [0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7]

# =====================================================================
# REGIONAI IR TAŠKAI (pavadinimas, platuma, ilguma)
# Taškus galima laisvai pridėti / išimti — pvz. jūsų maršrutų vietas.
# "match" — kurios Natural Earth teritorijos nuspalvinamos žemėlapyje.
# "label" — kur žemėlapyje dėti regiono užrašą (ilguma, platuma).
# =====================================================================
REGIONS = {
    "scotland": {
        "lt": "Škotija", "en": "Scotland",
        "match": [("GEOUNIT", "Scotland")],
        "label": (-14.6, 58.3),
        "points": [
            ("Edinburgas", 55.95, -3.19), ("Glazgas", 55.86, -4.25),
            ("M74 Beattock", 55.30, -3.47), ("Perth", 56.40, -3.43),
            ("Dundee", 56.46, -2.97), ("Aberdynas", 57.15, -2.09),
            ("Invernesas", 57.48, -4.22), ("A9 Drumochter", 56.85, -4.22),
            ("Fort William", 56.82, -5.11), ("Thurso", 58.59, -3.52),
            ("Cairnryan", 54.97, -5.02), ("Ullapool", 57.90, -5.16),
        ],
    },
    "england": {
        "lt": "Anglija", "en": "England",
        "match": [("GEOUNIT", "England")],
        "label": (1.2, 56.6),
        "points": [
            ("Kornvalis", 50.26, -5.05), ("Exeter", 50.72, -3.53),
            ("Portsmutas", 50.80, -1.09), ("Doveris", 51.13, 1.31),
            ("Londonas", 51.51, -0.13), ("Norwich", 52.63, 1.30),
            ("Birmingamas", 52.49, -1.89), ("Liverpulis", 53.41, -2.98),
            ("Lidsas", 53.80, -1.55), ("Hullas", 53.74, -0.33),
            ("M6 Shap", 54.53, -2.68), ("Niukaslas", 54.98, -1.62),
            ("Teesside", 54.58, -1.23),
        ],
    },
    "wales": {
        "lt": "Velsas", "en": "Wales",
        "match": [("GEOUNIT", "Wales")],
        "label": (-14.6, 50.2),
        "points": [
            ("Kardifas", 51.48, -3.18), ("Svonsis", 51.62, -3.94),
            ("Pembroke", 51.69, -4.94), ("Fishguard", 52.00, -4.98),
            ("Aberystwyth", 52.41, -4.08), ("Holyhead", 53.31, -4.63),
            ("A55 Deeside", 53.22, -3.05),
        ],
    },
    "ireland": {
        "lt": "Airija", "en": "Ireland",
        "match": [("ADMIN", "Ireland"), ("GEOUNIT", "Northern Ireland")],
        "label": (-14.6, 54.3),
        "points": [
            ("Dublinas", 53.35, -6.26), ("Rosslare", 52.25, -6.34),
            ("Korkas", 51.90, -8.47), ("Limerikas", 52.66, -8.63),
            ("Golvėjus", 53.27, -9.05), ("Sligo", 54.27, -8.47),
            ("Tralee", 52.27, -9.70), ("Atlonas", 53.42, -7.94),
            ("Belfastas", 54.60, -5.93), ("Derry", 55.00, -7.31),
        ],
    },
    "spain": {
        "lt": "Ispanija", "en": "Spain",
        "match": [("ADMIN", "Spain")],
        "label": (-14.6, 41.2),
        "points": [
            ("Bilbao", 43.26, -2.93), ("Santanderis", 43.46, -3.80),
            ("A Coruña", 43.37, -8.40), ("Vigo", 42.24, -8.72),
            ("Burgosas", 42.34, -3.70), ("Madridas", 40.42, -3.70),
            ("Saragosa", 41.65, -0.88), ("Lleida", 41.62, 0.62),
            ("Barselona", 41.39, 2.17), ("Valensija", 39.47, -0.38),
            ("Mursija", 37.98, -1.13), ("Almerija", 36.84, -2.46),
            ("Sevilija", 37.39, -5.98), ("Alchesirasas", 36.13, -5.45),
        ],
    },
    "france": {
        "lt": "Prancūzija", "en": "France",
        "match": [("ADMIN", "France")],
        "label": (-14.6, 46.6),
        "points": [
            ("Kalė", 50.95, 1.85), ("Lilis", 50.63, 3.06),
            ("Ruanas", 49.44, 1.10), ("Kanas", 49.18, -0.37),
            ("Brestas", 48.39, -4.49), ("Renas", 48.11, -1.68),
            ("Nantas", 47.22, -1.55), ("Paryžius", 48.86, 2.35),
            ("Reimsas", 49.26, 4.03), ("Strasbūras", 48.58, 7.75),
            ("Dižonas", 47.32, 5.04), ("Limožas", 45.83, 1.26),
            ("Bordo", 44.84, -0.58), ("Tulūza", 43.60, 1.44),
            ("Perpinjanas", 42.70, 2.90), ("Narbona", 43.18, 3.00),
            ("Monteliamaras (Ronos sl.)", 44.56, 4.75), ("Lionas", 45.76, 4.84),
            ("Marselis", 43.30, 5.37), ("Klermonas", 45.78, 3.08),
        ],
    },
    "netherlands": {
        "lt": "Nyderlandai", "en": "Netherlands",
        "match": [("ADMIN", "Netherlands")],
        "label": (3.6, 54.9),
        "points": [
            ("Amsterdamas", 52.37, 4.90), ("Roterdamas", 51.92, 4.48),
            ("Den Helderis", 52.96, 4.76), ("Afsluitdijk", 53.00, 5.10),
            ("Groningenas", 53.22, 6.57), ("Eindhovenas", 51.44, 5.48),
        ],
    },
    "belgium": {
        "lt": "Belgija", "en": "Belgium",
        "match": [("ADMIN", "Belgium")],
        "label": (-5.6, 49.2),
        "points": [
            ("Zeebrugge", 51.33, 3.20), ("Ostendė", 51.22, 2.92),
            ("Antverpenas", 51.22, 4.40), ("Briuselis", 50.85, 4.35),
            ("Lježas", 50.63, 5.57),
        ],
    },
    "luxembourg": {
        "lt": "Liuksemburgas", "en": "Luxembourg",
        "match": [("ADMIN", "Luxembourg")],
        "label": (15.6, 52.8),
        "points": [
            ("Liuksemburgas (m.)", 49.61, 6.13), ("Etelbriukas", 49.85, 6.10),
            ("Klervo", 50.05, 6.03), ("Eš prie Alzeto", 49.50, 5.98),
            ("Grevenmacheris", 49.68, 6.44),
        ],
    },
    "germany": {
        "lt": "Vokietija", "en": "Germany",
        "match": [("ADMIN", "Germany")],
        "label": (13.2, 56.2),
        "points": [
            ("Kylis", 54.32, 10.13), ("Rostokas", 54.09, 12.10),
            ("Hamburgas", 53.55, 10.00), ("Brėmenas", 53.08, 8.80),
            ("Berlynas", 52.52, 13.40), ("Hanoveris", 52.37, 9.73),
            ("Dortmundas", 51.51, 7.47), ("Kelnas", 50.94, 6.96),
            ("Kaselis", 51.31, 9.48), ("Leipcigas", 51.34, 12.37),
            ("Drezdenas", 51.05, 13.74), ("Frankfurtas", 50.11, 8.68),
            ("Niurnbergas", 49.45, 11.08), ("Štutgartas", 48.78, 9.18),
            ("Freiburgas", 47.99, 7.85), ("Miunchenas", 48.14, 11.58),
        ],
    },
    "austria": {
        "lt": "Austrija", "en": "Austria",
        "match": [("ADMIN", "Austria")],
        "label": (15.2, 50.7),
        "points": [
            ("Viena", 48.21, 16.37), ("Sankt Pöltenas", 48.20, 15.62),
            ("Lincas", 48.31, 14.29), ("Zalcburgas", 47.80, 13.04),
            ("Insbrukas", 47.27, 11.39), ("Brenerio p.", 47.00, 11.50),
            ("Bregencas", 47.50, 9.75), ("Gracas", 47.07, 15.44),
            ("Klagenfurtas", 46.62, 14.31), ("Filachas", 46.61, 13.85),
        ],
    },
    "switzerland": {
        "lt": "Šveicarija", "en": "Switzerland",
        "match": [("ADMIN", "Switzerland")],
        "label": (4.6, 41.4),
        "points": [
            ("Bazelis", 47.56, 7.59), ("Ciurichas", 47.37, 8.54),
            ("Bernas", 46.95, 7.45), ("Liucerna", 47.05, 8.31),
            ("Ženeva", 46.20, 6.14), ("Lozana", 46.52, 6.63),
            ("Sankt Galenas", 47.42, 9.37), ("Kuras", 46.85, 9.53),
            ("Lugano", 46.00, 8.95), ("Belincona", 46.19, 9.02),
            ("Airolo (Gotardas)", 46.53, 8.61), ("San Bernardino", 46.46, 9.19),
            ("Martinji", 46.10, 7.07), ("Sionas", 46.23, 7.36),
            ("Oltenas", 47.35, 7.90), ("Vinterturas", 47.50, 8.72),
            ("Nojšatelis", 46.99, 6.93),
        ],
    },
    "italy": {
        "lt": "Italija", "en": "Italy",
        "match": [("ADMIN", "Italy")],
        "label": (17.0, 43.9),
        "points": [
            ("Bolcanas", 46.50, 11.35), ("Milanas", 45.46, 9.19),
            ("Turinas", 45.07, 7.69), ("Verona", 45.44, 10.99),
            ("Triestas", 45.65, 13.78), ("Bolonija", 44.49, 11.34),
            ("Genuja", 44.41, 8.93), ("Florencija", 43.77, 11.25),
            ("Ankona", 43.62, 13.52), ("Roma", 41.90, 12.50),
            ("Fodža", 41.46, 15.54), ("Baris", 41.12, 16.87),
            ("Neapolis", 40.85, 14.27), ("Kaljaris", 39.22, 9.11),
            ("Redžas", 38.10, 15.65), ("Palermas", 38.12, 13.36),
            ("Katanija", 37.50, 15.09),
        ],
    },
}

# Papildomi miestai — naudojami kaip vietų pavadinimai tekste ir žemėlapyje.
EXTRA_PLACES = {
    "scotland": [("Stirling", 56.12, -3.94), ("Ayr", 55.46, -4.63), ("Oban", 56.41, -5.47),
                 ("Dumfries", 55.07, -3.61), ("Peterhead", 57.51, -1.78)],
    "england": [("Plymutas", 50.37, -4.14), ("Bristolis", 51.45, -2.59), ("Sautamptonas", 50.90, -1.40),
                ("Kembridžas", 52.21, 0.12), ("Notingemas", 52.95, -1.15), ("Mančesteris", 53.48, -2.24),
                ("Jorkas", 53.96, -1.08), ("Karlailas", 54.89, -2.93), ("Felikstou", 51.96, 1.35),
                ("Ipsvičas", 52.06, 1.16), ("Gloucesteris", 51.86, -2.24), ("Lesteris", 52.64, -1.13)],
    "wales": [("Brecon", 51.95, -3.39), ("Newtown", 52.51, -3.31), ("Bangoras", 53.23, -4.13)],
    "ireland": [("Waterfordas", 52.26, -7.11), ("Kilkenis", 52.65, -7.25), ("Donegolas", 54.65, -8.11),
                ("Mayo (Castlebar)", 53.85, -9.30), ("Dundalkas", 54.00, -6.40), ("Clare (Ennis)", 52.84, -8.98)],
    "spain": [("Chichonas", 43.53, -5.66), ("Ovjedas", 43.36, -5.85), ("Leonas", 42.60, -5.57),
              ("Valjadolidas", 41.65, -4.72), ("Salamanka", 40.97, -5.66), ("Kaseresas", 39.47, -6.37),
              ("Badachosas", 38.88, -6.97), ("Kordoba", 37.89, -4.78), ("Granada", 37.18, -3.60),
              ("Malaga", 36.72, -4.42), ("Kadisas", 36.53, -6.29), ("Huelva", 37.26, -6.95),
              ("Albasetė", 38.99, -1.86), ("Teruelis", 40.34, -1.11), ("Taragona", 41.12, 1.25),
              ("La Jonquera", 42.42, 2.87), ("Pamplona", 42.81, -1.64), ("Logronjas", 42.47, -2.45),
              ("Soria", 41.76, -2.47), ("Kuenka", 40.07, -2.14), ("Toledas", 39.86, -4.03),
              ("Siudad Realis", 38.98, -3.93), ("Alikantė", 38.35, -0.48), ("Kasteljonas", 39.99, -0.05),
              ("Lugas", 43.01, -7.56), ("Ourensas", 42.34, -7.86), ("Mérida", 38.92, -6.34),
              ("Chaenas", 37.77, -3.79), ("Gvadalachara", 40.63, -3.17), ("Uesca", 42.14, -0.41)],
    "france": [("Le Havras", 49.49, 0.11), ("Šerbūras", 49.64, -1.62), ("Sen Malo", 48.65, -2.03),
               ("Lorjanas", 47.75, -3.37), ("La Rošelis", 46.16, -1.15), ("Puatjė", 46.58, 0.34),
               ("Turas", 47.39, 0.69), ("Orleanas", 47.90, 1.90), ("Amjenas", 49.89, 2.30),
               ("Mecas", 49.12, 6.18), ("Nansi", 48.69, 6.18), ("Miulūzas", 47.75, 7.34),
               ("Bezansonas", 47.24, 6.02), ("Grenoblis", 45.19, 5.72), ("Valansas", 44.93, 4.89),
               ("Avinjonas", 43.95, 4.81), ("Nica", 43.70, 7.27), ("Tulonas", 43.12, 5.93),
               ("Monpeljė", 43.61, 3.88), ("Karkasonas", 43.21, 2.35), ("Bajona", 43.49, -1.47),
               ("Po", 43.30, -0.37), ("Brivas", 45.16, 1.53), ("Buržas", 47.08, 2.40),
               ("Trua", 48.30, 4.07), ("Bastija (Korsika)", 42.70, 9.45), ("Ajačas (Korsika)", 41.92, 8.74),
               ("Bulonė", 50.73, 1.61), ("Diunkerkas", 51.03, 2.38)],
    "netherlands": [("Utrechtas", 52.09, 5.12), ("Arnhemas", 51.98, 5.91), ("Vlisingenas", 51.44, 3.57),
                    ("Leuvardenas", 53.20, 5.80), ("Venlo", 51.37, 6.17), ("Zvolė", 52.52, 6.08),
                    ("Hagos", 52.07, 4.30), ("Mastrichtas", 50.85, 5.69)],
    "belgium": [("Gentas", 51.05, 3.72), ("Namiūras", 50.47, 4.87), ("Bastonė", 50.00, 5.72),
                ("Šarlerua", 50.41, 4.44), ("Hasseltas", 50.93, 5.34), ("Kortreikas", 50.83, 3.27),
                ("Arlonas", 49.68, 5.82)],
    "germany": [("Flensburgas", 54.79, 9.44), ("Emdenas", 53.37, 7.21), ("Kukshafenas", 53.86, 8.69),
                ("Liubekas", 53.87, 10.69), ("Štralzundas", 54.31, 13.09), ("Osnabriukas", 52.28, 8.05),
                ("Magdeburgas", 52.13, 11.63), ("Erfurtas", 50.98, 11.03), ("Kemnicas", 50.83, 12.92),
                ("Vircburgas", 49.79, 9.95), ("Manheimas", 49.49, 8.47), ("Saarbriukenas", 49.24, 6.99),
                ("Koblencas", 50.36, 7.59), ("Regensburgas", 49.01, 12.10), ("Augsburgas", 48.37, 10.90),
                ("Ulmas", 48.40, 9.99), ("Pasau", 48.57, 13.43), ("Fiusenas", 47.57, 10.70),
                ("Getingenas", 51.54, 9.93), ("Frankfurtas prie Oderio", 52.34, 14.55)],
    "austria": [("Velsas (AT)", 48.16, 14.03), ("Kufšteinas", 47.58, 12.17), ("Landekas", 47.14, 10.57),
                ("Lincas–Amstetenas", 48.12, 14.87), ("Viener Noištatas", 47.81, 16.25),
                ("Liencas", 46.83, 12.77), ("Leobenas", 47.38, 15.09)],
    "italy": [("Aosta", 45.74, 7.32), ("Komas", 45.81, 9.09), ("Bergamas", 45.70, 9.67),
              ("Brešija", 45.54, 10.21), ("Trentas", 46.07, 11.12), ("Padova", 45.41, 11.88),
              ("Venecija", 45.44, 12.32), ("Udinė", 46.06, 13.24), ("Parma", 44.80, 10.33),
              ("Pjačenca", 45.05, 9.69), ("Ravena", 44.42, 12.20), ("Riminis", 44.06, 12.57),
              ("La Specija", 44.10, 9.82), ("Livornas", 43.55, 10.31), ("Peskara", 42.46, 14.21),
              ("Perudža", 43.11, 12.39), ("Čivitavekija", 42.09, 11.80), ("Salernas", 40.68, 14.77),
              ("Taranas", 40.46, 17.25), ("Brindizis", 40.63, 17.94), ("Kozenca", 39.30, 16.25),
              ("Mesina", 38.19, 15.55), ("Trapanis", 38.02, 12.51), ("Sasaris", 40.73, 8.56),
              ("Olbija", 40.92, 9.50), ("Kunėjus", 44.38, 7.54), ("Alesandrija", 44.91, 8.61)],
}
for _rk, _extra in EXTRA_PLACES.items():
    REGIONS[_rk]["points"].extend(_extra)

# Spalvos pagal balą
BFT_COLORS = {8: "#ffc61a", 9: "#f76707", 10: "#d9282f", 11: "#7a1020"}  # 11 = 11 ir daugiau
REGION_FILL = "#fbfaf6"   # stebimų šalių fonas
OTHER_LAND = "#e2e2e2"
SEA = "#dfeaf3"

TEXT = {
    "lt": {
        "gusts": "gūsiai", "up_to": "iki",
        "title": "Vėjo gūsių įspėjimai ≥{bft} Bft",
        "period": "Laikotarpis",
        "no_warn": "Be įspėjimų",
        "none_at_all": "Laikotarpiu vėjo gūsiai nesieks {bft} Bft nė viename regione.",
        "now": "prasideda anksčiau", "later": "tęsiasi ir vėliau",
        "region": "Regionas", "max": "Gūsiai", "when": "Laikotarpis", "places": "Vietos",
        "source": "Duomenys: Open-Meteo.com (CC BY 4.0), modelis {model}. Sienos: Natural Earth. Sugeneruota {ts}.",
        "legend_quiet": "< {bft} Bft",
        "hour": "val.",
    },
    "en": {
        "gusts": "gusts", "up_to": "up to",
        "title": "Wind gust warnings ≥{bft} Bft",
        "period": "Period",
        "no_warn": "No warnings",
        "none_at_all": "Wind gusts will not reach {bft} Bft in any region during this period.",
        "now": "starts earlier", "later": "continues after",
        "region": "Region", "max": "Gusts", "when": "Period", "places": "Places",
        "source": "Data: Open-Meteo.com (CC BY 4.0), model {model}. Borders: Natural Earth. Generated {ts}.",
        "legend_quiet": "< {bft} Bft",
        "hour": "h",
    },
}


# =====================================================================
# Žemėlapio sienos ir taškų tinklelis
# =====================================================================
def load_geojson(path_arg=None):
    path = Path(path_arg) if path_arg else GEOJSON_CACHE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if path_arg:
        print(f"! Nerastas {path}", file=sys.stderr)
        return None
    try:
        r = requests.get(GEOJSON_URL, timeout=90)
        r.raise_for_status()
        GEOJSON_CACHE.write_bytes(r.content)
        return r.json()
    except Exception as ex:  # noqa: BLE001
        print(f"! Nepavyko atsisiųsti sienų žemėlapio ({ex}).\n"
              f"  Bus naudojami tik pavadinti miestai, be tinklelio.", file=sys.stderr)
        return None


def feature_region(props):
    for rk, reg in REGIONS.items():
        for field, val in reg["match"]:
            if props.get(field) == val or props.get(field.lower()) == val:
                return rk
    return None


def exterior_rings(geom):
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def region_rings(geo):
    """{region: [ring, ...]} tik žemėlapio ribose esantiems poligonams."""
    out = {rk: [] for rk in REGIONS}
    if not geo:
        return out
    x0, x1, y0, y1 = MAP_EXTENT
    for f in geo["features"]:
        rk = feature_region(f.get("properties", {}))
        if not rk:
            continue
        for ring in exterior_rings(f.get("geometry")):
            xs = [c[0] for c in ring]
            ys = [c[1] for c in ring]
            if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                continue
            out[rk].append(ring)
    return out


def km(lat1, lon1, lat2, lon2):
    """Apytikslis atstumas km."""
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110.57
    return math.hypot(dx, dy)


def build_points(rings):
    """
    Grąžina taškų sąrašą: dict(id, region, lat, lon, name, place).
    name  – miesto pavadinimas (pavadintiems taškams) arba None (tinklelio taškams)
    place – artimiausias to paties regiono miestas (naudojamas tekste ir žemėlapyje)
    """
    pts = []
    for rk, reg in REGIONS.items():
        named = reg["points"]
        for name, lat, lon in named:
            pts.append({"id": f"{rk}:{name}", "region": rk, "lat": lat, "lon": lon,
                        "name": name, "place": name})
        paths = [MplPath(np.array(r)) for r in rings.get(rk, [])]
        if not paths:
            continue
        allx = [c[0] for r in rings[rk] for c in r]
        ally = [c[1] for r in rings[rk] for c in r]
        x0 = math.floor(max(min(allx), MAP_EXTENT[0]) / GRID_STEP) * GRID_STEP + GRID_STEP / 2
        y0 = math.floor(max(min(ally), MAP_EXTENT[2]) / GRID_STEP) * GRID_STEP + GRID_STEP / 2
        x1 = min(max(allx), MAP_EXTENT[1])
        y1 = min(max(ally), MAP_EXTENT[3])
        for lat in np.arange(y0, y1 + 1e-9, GRID_STEP):
            for lon in np.arange(x0, x1 + 1e-9, GRID_STEP):
                if any(p.contains_point((lon, lat)) for p in paths):
                    nearest = min(named, key=lambda n: km(lat, lon, n[1], n[2]))[0]
                    pts.append({"id": f"{rk}:g{lat:.2f},{lon:.2f}", "region": rk,
                                "lat": round(float(lat), 3), "lon": round(float(lon), 3),
                                "name": None, "place": nearest})
    return pts


# =====================================================================
# Duomenų gavimas
# =====================================================================
RETRY_WAITS = [30, 60, 120, 240]   # sekundės tarp pakartotinių bandymų (iš viso ~7,5 min.)


def _get_with_retry(url, params, label=""):
    """
    Užklausa su pakartojimais: jei Open-Meteo laikinai nepasiekiamas (timeout, ryšio klaida,
    5xx ar 429), palaukiama ir bandoma dar kartą. Tik po visų nesėkmių metama klaida.
    """
    last_err = None
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            r = requests.get(url, params=params, timeout=(20, 120))  # 20 s prisijungti, 120 s atsakymui
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"HTTP {r.status_code}"
            else:
                r.raise_for_status()
                return r.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as ex:
            last_err = type(ex).__name__
        if attempt < len(RETRY_WAITS):
            wait = RETRY_WAITS[attempt]
            print(f"! Open-Meteo ({label}): {last_err}. Bandau dar kartą po {wait} s...",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Open-Meteo nepasiekiamas po {len(RETRY_WAITS) + 1} bandymų ({label}): {last_err}")


def fetch_open_meteo(points, chunk=100):
    """Grąžina DataFrame (laikas × taško id): vėjo gūsiai, m/s."""
    base = ("https://customer-api.open-meteo.com/v1/forecast" if API_KEY
            else "https://api.open-meteo.com/v1/forecast")
    cols = {}
    for i in range(0, len(points), chunk):
        part = points[i:i + chunk]
        params = {
            "latitude": ",".join(f"{p['lat']:.3f}" for p in part),
            "longitude": ",".join(f"{p['lon']:.3f}" for p in part),
            "hourly": "wind_gusts_10m",
            "wind_speed_unit": "ms",
            "timezone": TIMEZONE,
            "forecast_days": FORECAST_DAYS,
            "models": MODEL,
        }
        if API_KEY:
            params["apikey"] = API_KEY
        data = _get_with_retry(base, params, label=f"taškai {i + 1}–{i + len(part)}")
        if isinstance(data, dict):
            data = [data]
        for p, d in zip(part, data):
            idx = pd.to_datetime(d["hourly"]["time"])
            cols[p["id"]] = pd.Series(d["hourly"]["wind_gusts_10m"], index=idx, dtype=float)
        # Nemokama versija: ne daugiau 600 taškų per minutę -> 100 taškų kas ~12 s.
        if not API_KEY and i + chunk < len(points):
            time.sleep(12)
    return pd.DataFrame(cols)


def demo_data(points, day):
    """Bandomieji duomenys: audra slenka iš vakarų į rytus + vėjai pietų Prancūzijoje ir Ispanijoje."""
    idx = pd.date_range(day, periods=24 * FORECAST_DAYS, freq="h")
    t = np.arange(len(idx))
    rng = np.random.default_rng(1)
    cols = {}
    for p in points:
        lat, lon = p["lat"], p["lon"]
        peak_t = 22 + (lon + 10) * 1.6
        strength = max(0.0, (lat - 48.5) / 8)
        g = 14 * strength * np.exp(-((t - peak_t) ** 2) / (2 * 8 ** 2))
        if 42.5 < lat < 45 and 2.5 < lon < 5.5:                       # mistralis / tramontana
            g = g + 12 * np.exp(-((t - 26) ** 2) / (2 * 7 ** 2))
        if 36.0 < lat < 38.5 and -3.5 < lon < -0.5:                   # levantas Almerijos pusėje
            g = g + 12 * np.exp(-((t - 18) ** 2) / (2 * 6 ** 2)) * (1 - abs(lon + 2) / 1.5)
        base = 7 + 3 * np.sin(t / 7 + lon) + rng.normal(0, 0.8, len(t))
        cols[p["id"]] = pd.Series(np.clip(base + g, 0, None) * 1.05, index=idx)
    return pd.DataFrame(cols)


# =====================================================================
# Skaičiavimai
# =====================================================================
def to_bft(ms):
    """m/s -> Boforto balas (0–12)."""
    arr = np.nan_to_num(np.asarray(ms, dtype=float), nan=0.0)
    return np.searchsorted(BFT_LIMITS, arr, side="right")


def find_intervals(mask: pd.Series, gap_h: int):
    """Grąžina [(pradžia, pabaiga)] iš eilės einančioms valandoms, kur mask=True."""
    times = list(mask.index[mask.values])
    if not times:
        return []
    out = [[times[0], times[0]]]
    for tm in times[1:]:
        if (tm - out[-1][1]) <= pd.Timedelta(hours=gap_h + 1):
            out[-1][1] = tm
        else:
            out.append([tm, tm])
    return [tuple(x) for x in out]


def analyse(gust, points, t_from, t_to):
    """Kiekvienam regionui: laikotarpiai, maks. balas, vietos, taškų maksimumai."""
    sel = (gust.index >= t_from) & (gust.index <= t_to)
    g_win = gust[sel]
    by_region = {rk: [p for p in points if p["region"] == rk] for rk in REGIONS}
    res = {}
    for rk, rpts in by_region.items():
        ids = [p["id"] for p in rpts if p["id"] in g_win.columns]
        place_of = {p["id"]: p["place"] for p in rpts}
        ms = g_win[ids]
        bft = pd.DataFrame(to_bft(ms.values), index=ms.index, columns=ids)
        region_bft = bft.max(axis=1) if ids else pd.Series(dtype=int)

        def exceeds_at(t):
            if t not in gust.index or not ids:
                return False
            return int(to_bft(gust.loc[t, ids].values).max()) >= MIN_BFT

        intervals = []
        for a, b in find_intervals(region_bft >= MIN_BFT, MERGE_GAP_HOURS):
            seg = bft.loc[a:b]
            peak_by_id = seg.max(axis=0)
            hot = peak_by_id[peak_by_id >= MIN_BFT]
            place_info = {}   # vieta -> [maks. balas, pirma valanda, paskutinė valanda]
            for pid, v in hot.items():
                pl = place_of[pid]
                hrs = seg.index[seg[pid].values >= MIN_BFT]
                info = place_info.setdefault(pl, [0, hrs.min(), hrs.max()])
                info[0] = max(info[0], int(v))
                info[1] = min(info[1], hrs.min())
                info[2] = max(info[2], hrs.max())
            places = sorted(((pl, i[0], i[1], i[2]) for pl, i in place_info.items()),
                            key=lambda x: (-x[1], x[2], x[0]))
            intervals.append({
                "start": a, "end": b,
                "bft": int(seg.values.max()),
                "ms": float(ms.loc[a:b].values.max()),
                "places": places,
                "open_start": a <= g_win.index.min() and exceeds_at(a - pd.Timedelta(hours=1)),
                "open_end": b >= g_win.index.max() and exceeds_at(b + pd.Timedelta(hours=1)),
            })
        point_peak = {pid: int(bft[pid].max()) for pid in ids}
        point_ms = {pid: float(ms[pid].max()) for pid in ids}
        res[rk] = {"intervals": intervals,
                   "max_bft": int(region_bft.max()) if len(region_bft) else 0,
                   "point_peak": point_peak, "point_ms": point_ms}
    return res


# =====================================================================
# Tekstas ir HTML
# =====================================================================
def fmt_t(ts):
    return ts.strftime("%m.%d %H:%M")


def fmt_t_short(ts):
    return ts.strftime("%m.%d %H")


def interval_str(iv, lang):
    T = TEXT[lang]
    s = fmt_t(iv["start"]) if iv["start"] == iv["end"] else f"{fmt_t(iv['start'])} – {fmt_t(iv['end'])}"
    extras = ([T["now"]] if iv["open_start"] else []) + ([T["later"]] if iv["open_end"] else [])
    return s + (" (" + ", ".join(extras) + ")" if extras else "")


def strength_str(iv, lang):
    T = TEXT[lang]
    return f"{T['gusts']} {T['up_to']} {iv['bft']} Bft ({iv['ms']:.0f} m/s)"


def span_str(a, b, lang):
    if a == b:
        return f"{a:%m.%d %H}:00"
    if a.date() == b.date():
        return f"{a:%m.%d %H}:00–{b:%H}:00"
    return f"{a:%m.%d %H}:00–{b:%m.%d %H}:00"


def place_lines(iv, lang="lt"):
    """Vietų sąrašas: viena eilutė vienai vietai."""
    shown = iv["places"][:MAX_PLACES_TEXT]
    out = [f"{name} – {b} Bft, {span_str(a, e, lang)}" for name, b, a, e in shown]
    rest = len(iv["places"]) - MAX_PLACES_TEXT
    if rest > 0:
        out.append(f"+{rest} " + ("kitos vietos" if lang == "lt" else "more places"))
    return out


def build_text(res, lang, t_from, t_to):
    T = TEXT[lang]
    lines = [T["title"].format(bft=MIN_BFT),
             f"{T['period']}: {fmt_t(t_from)} – {fmt_t(t_to)} ({TZ_LABEL[lang]})", ""]
    quiet = []
    order = sorted(REGIONS, key=lambda rk: -res[rk]["max_bft"])
    for rk in order:
        r = res[rk]
        if not r["intervals"]:
            quiet.append(REGIONS[rk][lang])
            continue
        lines.append(f"{REGIONS[rk][lang]}:")
        for iv in r["intervals"]:
            lines.append(f"  • {interval_str(iv, lang)} — {strength_str(iv, lang)}")
            lines += [f"      {pl}" for pl in place_lines(iv, lang)]
    if len(quiet) == len(REGIONS):
        lines.append(T["none_at_all"].format(bft=MIN_BFT))
    elif quiet:
        lines += ["", f"{T['no_warn']}: {', '.join(REGIONS[rk][lang] for rk in REGIONS if REGIONS[rk][lang] in quiet)}"]
    return "\n".join(lines)


def build_email_json(res, lang, t_from, t_to, ts, map_path, today):
    """Microsoft Graph sendMail užklausa: HTML tekstas + žemėlapis tiesiai laiške (inline)."""
    img = ""
    attachments = []
    if map_path and Path(map_path).exists():
        img = ('<p><img src="cid:vejo_zemelapis" width="760" alt="Vėjo gūsių žemėlapis" '
               'style="max-width:100%;height:auto;border:1px solid #ddd"></p>')
        attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "vejo_zemelapis.png",
            "contentType": "image/png",
            "contentId": "vejo_zemelapis",
            "isInline": True,
            "contentBytes": base64.b64encode(Path(map_path).read_bytes()).decode("ascii"),
        })
    body_html = build_html(res, lang, t_from, t_to, ts, img_html=img)
    msg = {
        "subject": f"{EMAIL_SUBJECT[lang]} {today:%Y-%m-%d}",
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in EMAIL_TO],
        "attachments": attachments,
    }
    if EMAIL_BCC:
        msg["bccRecipients"] = [{"emailAddress": {"address": a}} for a in EMAIL_BCC]
    return {"message": msg, "saveToSentItems": True}


def build_html(res, lang, t_from, t_to, ts, img_html=""):
    T = TEXT[lang]
    e = html.escape
    td = 'style="padding:6px 10px;border:1px solid #ddd;vertical-align:top"'
    rows, quiet = [], []
    order = sorted(REGIONS, key=lambda rk: -res[rk]["max_bft"])
    for rk in order:
        ivs = res[rk]["intervals"]
        if not ivs:
            quiet.append(REGIONS[rk][lang])
            continue
        for i, iv in enumerate(ivs):
            col = bft_color(iv["bft"])
            fg = "#3d2c00" if iv["bft"] <= 8 else "#fff"
            name_cell = (f'<td rowspan="{len(ivs)}" style="padding:6px 10px;border:1px solid #ddd;'
                         f'font-weight:bold;vertical-align:top">{e(REGIONS[rk][lang])}</td>') if i == 0 else ""
            rows.append(
                "<tr>" + name_cell +
                f'<td style="padding:6px 10px;border:1px solid #ddd;background:{col};color:{fg};'
                f'font-weight:bold;text-align:center;white-space:nowrap">{iv["bft"]} Bft<br>'
                f'<span style="font-weight:normal;font-size:11px">{iv["ms"]:.0f} m/s</span></td>'
                f'<td {td}>{e(interval_str(iv, lang))}</td>'
                f'<td {td}>{"<br>".join(e(x) for x in place_lines(iv, lang))}</td></tr>')
    head = (f'<p style="font-family:Arial,sans-serif;font-size:14px"><b>'
            f'{e(T["title"].format(bft=MIN_BFT))}</b><br>'
            f'{e(T["period"])}: {e(fmt_t(t_from))} – {e(fmt_t(t_to))} ({e(TZ_LABEL[lang])})</p>')
    if rows:
        th = 'style="padding:6px 10px;border:1px solid #ddd;text-align:left"'
        table = ('<table style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px">'
                 f'<tr style="background:#f3f3f3"><th {th}>{e(T["region"])}</th><th {th}>{e(T["max"])}</th>'
                 f'<th {th}>{e(T["when"])}</th><th {th}>{e(T["places"])}</th></tr>'
                 + "".join(rows) + "</table>")
    else:
        table = f'<p style="font-family:Arial,sans-serif">{e(T["none_at_all"].format(bft=MIN_BFT))}</p>'
    q = (f'<p style="font-family:Arial,sans-serif;font-size:13px;color:#555">'
         f'{e(T["no_warn"])}: {e(", ".join(quiet))}</p>') if quiet and rows else ""
    src = (f'<p style="font-family:Arial,sans-serif;font-size:11px;color:#888">'
           f'{e(T["source"].format(model=MODEL, ts=ts))}</p>')
    return head + img_html + table + q + src


# =====================================================================
# Žemėlapis
# =====================================================================
def bft_color(b):
    return BFT_COLORS.get(min(b, 11), BFT_COLORS[8])


def _fill_nan_outward(Z, steps=2):
    """Užpildo NaN langelius prie sienos kaimynų maksimumu, kad zonos siektų pakrantę."""
    Z = Z.copy()
    for _ in range(steps):
        P = np.pad(Z, 1, constant_values=np.nan)
        neigh = np.stack([P[1 + dy:P.shape[0] - 1 + dy, 1 + dx:P.shape[1] - 1 + dx]
                          for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx])
        with np.errstate(all="ignore"):
            nb = np.nanmax(np.where(np.isnan(neigh), -np.inf, neigh), axis=0)
        nb[np.isinf(nb)] = np.nan
        mask = np.isnan(Z) & ~np.isnan(nb)
        Z[mask] = nb[mask]
    return Z


def _land_clip_patch(ax, rings):
    """Visų stebimų šalių ribos kaip vienas kirpimo kontūras."""
    from matplotlib.patches import PathPatch
    paths = [MplPath(np.array(r)) for rr in rings.values() for r in rr]
    if not paths:
        return None
    compound = MplPath.make_compound_path(*paths)
    patch = PathPatch(compound, transform=ax.transData, facecolor="none", edgecolor="none")
    ax.add_patch(patch)
    return patch


def make_map(res, points, geo, lang, t_from, t_to, path, ts):
    T = TEXT[lang]
    x0, x1, y0, y1 = MAP_EXTENT
    fig = plt.figure(figsize=(15, 10.5), dpi=130)
    ax = fig.add_axes([0.01, 0.04, 0.66, 0.86])
    side = fig.add_axes([0.685, 0.04, 0.305, 0.86])
    side.axis("off")
    ax.set_facecolor(SEA)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / math.cos(math.radians(48)))
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#c8c8c8")
    halo = [pe.withStroke(linewidth=3.2, foreground="white")]

    # 1. Šalys: stebimos – šviesios, kitos – pilkos
    rings = region_rings(geo)
    if geo:
        for f in geo["features"]:
            rk = feature_region(f.get("properties", {}))
            for ring in exterior_rings(f.get("geometry")):
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
                if max(xs) < x0 - 5 or min(xs) > x1 + 5 or max(ys) < y0 - 5 or min(ys) > y1 + 5:
                    continue
                ax.add_patch(Polygon(list(zip(xs, ys)), closed=True,
                                     facecolor=REGION_FILL if rk else OTHER_LAND,
                                     edgecolor="none", zorder=1))

    # 2. Pavojingos zonos – glotnios spalvotos zonos (ne langeliai)
    pmap = {p["id"]: p for p in points}
    grid = [(p["lon"], p["lat"], res[p["region"]]["point_ms"].get(p["id"], np.nan))
            for p in points if p["name"] is None]
    if grid:
        lons = np.unique(np.round([g[0] for g in grid], 3))
        lats = np.unique(np.round([g[1] for g in grid], 3))
        lon_full = np.arange(lons.min() - GRID_STEP, lons.max() + 2 * GRID_STEP, GRID_STEP)
        lat_full = np.arange(lats.min() - GRID_STEP, lats.max() + 2 * GRID_STEP, GRID_STEP)
        Z = np.full((len(lat_full), len(lon_full)), np.nan)
        for lo, la, v in grid:
            i = int(round((la - lat_full[0]) / GRID_STEP))
            j = int(round((lo - lon_full[0]) / GRID_STEP))
            Z[i, j] = v
        Z = _fill_nan_outward(Z, steps=2)
        Zf = np.nan_to_num(Z, nan=0.0)
        try:   # glotninimas – 4 kartus tankesnis tinklelis
            from scipy.ndimage import zoom
            Zf = zoom(Zf, 4, order=1)
            lon_f = np.linspace(lon_full[0], lon_full[-1], Zf.shape[1])
            lat_f = np.linspace(lat_full[0], lat_full[-1], Zf.shape[0])
        except ImportError:
            lon_f, lat_f = lon_full, lat_full
        levels = [BFT_LIMITS[MIN_BFT - 1]] + [BFT_LIMITS[b - 1] for b in range(MIN_BFT + 1, 12)] + [99]
        colors = [bft_color(b) for b in range(MIN_BFT, MIN_BFT + len(levels) - 1)]
        cs = ax.contourf(lon_f, lat_f, Zf, levels=levels, colors=colors, alpha=0.85, zorder=2)
        clip = _land_clip_patch(ax, rings)
        if clip is not None:
            for coll in getattr(cs, "collections", [cs]):
                coll.set_clip_path(clip)
    else:   # be sienų failo – tik miestų taškai
        for rk in REGIONS:
            for pid, b in res[rk]["point_peak"].items():
                if b >= MIN_BFT:
                    p = pmap[pid]
                    ax.scatter(p["lon"], p["lat"], s=160, color=bft_color(b), alpha=0.85,
                               edgecolor="none", zorder=2)

    # 3. Sienos virš zonų
    if geo:
        for f in geo["features"]:
            rk = feature_region(f.get("properties", {}))
            for ring in exterior_rings(f.get("geometry")):
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
                if max(xs) < x0 - 5 or min(xs) > x1 + 5 or max(ys) < y0 - 5 or min(ys) > y1 + 5:
                    continue
                ax.plot(xs, ys, color="#6f6f6f" if rk else "#b0b0b0",
                        linewidth=0.7 if rk else 0.4, zorder=3)

    # 4. Tik svarbiausi miestai: po MAX_LABELS_MAP stipriausius kiekvienoje šalyje
    placed = []

    def free(bx0, by0, bx1, by1):
        return all(bx1 < a0 or bx0 > a1 or by1 < b0 or by0 > b1 for a0, b0, a1, b1 in placed)

    candidates = []
    for rk, reg in REGIONS.items():
        place_peak = {}
        for iv in res[rk]["intervals"]:
            for name, b, *_ in iv["places"]:
                place_peak[name] = max(place_peak.get(name, 0), b)
        top = sorted(place_peak.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_LABELS_MAP]
        coords = {n: (lat, lon) for n, lat, lon in reg["points"]}
        candidates += [(b, n, *coords[n]) for n, b in top]
    for b, name, lat, lon in sorted(candidates, key=lambda c: -c[0]):
        label = name.split(" (")[0]
        w, h = len(label) * 0.19, 0.5
        for tx, ty, ha in [(lon + 0.2, lat + 0.05, "left"), (lon - 0.2, lat + 0.05, "right"),
                           (lon + 0.2, lat - 0.5, "left"), (lon - 0.2, lat - 0.5, "right")]:
            bx0, bx1 = (tx, tx + w) if ha == "left" else (tx - w, tx)
            if free(bx0, ty, bx1, ty + h):
                placed.append((bx0, ty, bx1, ty + h))
                ax.scatter(lon, lat, s=20, color="#1f1f1f", edgecolor="white", linewidth=0.8, zorder=5)
                ax.text(tx, ty, label, fontsize=9, ha=ha, va="bottom", color="#1f1f1f",
                        zorder=6, path_effects=halo)
                break

    # 5. Šoninė santrauka: šalys pagal stiprumą
    ax.set_title(T["title"].format(bft=MIN_BFT), fontsize=16, fontweight="bold", loc="left", pad=24)
    ax.text(0, 1.012, f"{fmt_t(t_from)} – {fmt_t(t_to)} ({TZ_LABEL[lang]})", transform=ax.transAxes,
            fontsize=12, color="#444444", va="bottom")
    order = sorted(REGIONS, key=lambda rk: (-res[rk]["max_bft"], REGIONS[rk][lang]))
    y = 0.985
    side.text(0, y, T["region"] if lang == "en" else "Šalys", fontsize=12, fontweight="bold",
              va="top", transform=side.transAxes)
    y -= 0.045
    quiet = []
    for rk in order:
        r = res[rk]
        if not r["intervals"]:
            quiet.append(REGIONS[rk][lang])
            continue
        b = r["max_bft"]
        side.add_patch(Rectangle((0, y - 0.024), 0.085, 0.03, transform=side.transAxes,
                                 facecolor=bft_color(b), edgecolor="none"))
        side.text(0.0425, y - 0.009, str(b), transform=side.transAxes, ha="center", va="center",
                  fontsize=10.5, fontweight="bold", color="white" if b >= 9 else "#3d2c00")
        side.text(0.11, y - 0.009, REGIONS[rk][lang], transform=side.transAxes, va="center",
                  fontsize=11, fontweight="bold")
        y -= 0.034
        for iv in r["intervals"][:3]:
            if iv["start"] == iv["end"]:
                txt = fmt_t(iv["start"])
            elif iv["start"].date() == iv["end"].date():
                txt = f"{fmt_t(iv['start'])}–{iv['end']:%H:%M}"
            else:
                txt = f"{fmt_t(iv['start'])} – {fmt_t(iv['end'])}"
            side.text(0.11, y, txt, transform=side.transAxes, va="center", fontsize=9.5, color="#444444")
            y -= 0.027
        if len(r["intervals"]) > 3:
            side.text(0.11, y, f"+{len(r['intervals']) - 3}", transform=side.transAxes,
                      va="center", fontsize=9, color="#777777")
            y -= 0.027
        y -= 0.012
    if quiet:
        y -= 0.01
        side.text(0, y, f"{T['no_warn']}:", transform=side.transAxes, va="top", fontsize=10,
                  fontweight="bold", color="#555555")
        side.text(0, y - 0.03, "\n".join(_wrap(", ".join(quiet), 42)), transform=side.transAxes,
                  va="top", fontsize=10, color="#555555", linespacing=1.4)

    # 6. Legenda
    handles = []
    for b in range(MIN_BFT, 12):
        if b == 11:
            rng_txt = f"≥{BFT_LIMITS[10]:.1f}"
            lab = f"11+ Bft ({rng_txt} m/s)"
        else:
            lab = f"{b} Bft ({BFT_LIMITS[b - 1]:.1f}–{BFT_LIMITS[b] - 0.1:.1f} m/s)"
        handles.append(Patch(facecolor=bft_color(b), alpha=0.85, label=lab))
    ax.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.95,
              title=T["gusts"].capitalize(), title_fontsize=9)
    fig.text(0.01, 0.012, T["source"].format(model=MODEL, ts=ts), fontsize=7.5, color="#888888")
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def _wrap(text, width):
    words, lines, cur = text.split(", "), [], ""
    for w in words:
        add = (", " if cur else "") + w
        if len(cur) + len(add) > width and cur:
            lines.append(cur + ",")
            cur = w
        else:
            cur += add
    if cur:
        lines.append(cur)
    return lines


# =====================================================================
# Pagrindinė dalis
# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Vėjo gūsių (Boforto) įspėjimai")
    ap.add_argument("--lang", choices=["lt", "en"], default="lt")
    ap.add_argument("--date", help="ataskaitos data YYYY-MM-DD (numatyta: šiandien)")
    ap.add_argument("--demo", action="store_true", help="bandomieji duomenys be orų API")
    ap.add_argument("--geojson", help="vietinis sienų GeoJSON failas (nebūtina)")
    ap.add_argument("--no-map", action="store_true")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Visada: šiandien 08:00 – rytoj 13:00 (nepriklausomai nuo paleidimo laiko)
    today = pd.Timestamp(args.date) if args.date else \
        pd.Timestamp(dt.datetime.now(ZoneInfo(TIMEZONE)).date())
    t_from = today + pd.Timedelta(hours=WINDOW_START_HOUR)
    days_ahead = 3 if (FRIDAY_UNTIL_MONDAY and today.weekday() == 4) else 1  # 4 = penktadienis
    t_to = today + pd.Timedelta(days=days_ahead, hours=WINDOW_END_HOUR)
    ts = dt.datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M")

    geo = load_geojson(args.geojson)
    points = build_points(region_rings(geo))
    n_grid = sum(p["name"] is None for p in points)
    print(f"Taškų: {len(points)} (tinklelio {n_grid}, miestų {len(points) - n_grid})", file=sys.stderr)

    gust = demo_data(points, today) if args.demo else fetch_open_meteo(points)

    res = analyse(gust, points, t_from, t_to)
    text = build_text(res, args.lang, t_from, t_to)
    (OUTPUT_DIR / "vejo_ispejimai.txt").write_text(text, encoding="utf-8")
    (OUTPUT_DIR / "vejo_ispejimai.html").write_text(
        build_html(res, args.lang, t_from, t_to, ts), encoding="utf-8")
    print(text)

    if not args.no_map:
        make_map(res, points, geo, args.lang, t_from, t_to,
                 OUTPUT_DIR / "vejo_zemelapis.png", ts)
    if EMAIL_TO or EMAIL_BCC:
        mail = build_email_json(res, args.lang, t_from, t_to, ts,
                                None if args.no_map else OUTPUT_DIR / "vejo_zemelapis.png", today)
        (OUTPUT_DIR / "vejo_laiskas.json").write_text(
            json.dumps(mail, ensure_ascii=False), encoding="utf-8")
    else:
        print("! EMAIL_TO tuščias – vejo_laiskas.json nesukurtas.", file=sys.stderr)
    print(f"\nFailai išsaugoti: {OUTPUT_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
