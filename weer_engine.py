# -*- coding: utf-8 -*-
"""weer_engine.py - de weermotor van DraveWeer (ook gebruikt in DraveWeer voor Android).

Gratis weergegevens via Open-Meteo (geen API-sleutel nodig):
- stad zoeken (geocoding)
- huidig weer, 7-daagse verwachting en uurverwachting

Alles met de Python-standaardbibliotheek (urllib), dus geen extra installaties.
"""
import json
import urllib.parse
import urllib.request

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FC_URL = "https://api.open-meteo.com/v1/forecast"

# WMO-weercodes -> (nederlandse omschrijving, icoon-categorie)
# icoon-categorieen: zon, halfbewolkt, bewolkt, mist, motregen, regen, sneeuw,
#                    buien, onweer
WMO = {
    0: ("Helder", "zon"),
    1: ("Overwegend helder", "halfbewolkt"),
    2: ("Half bewolkt", "halfbewolkt"),
    3: ("Bewolkt", "bewolkt"),
    45: ("Mistig", "mist"),
    48: ("Mist met rijp", "mist"),
    51: ("Lichte motregen", "motregen"),
    53: ("Motregen", "motregen"),
    55: ("Dichte motregen", "motregen"),
    56: ("Lichte ijzel", "motregen"),
    57: ("IJzel", "motregen"),
    61: ("Lichte regen", "regen"),
    63: ("Regen", "regen"),
    65: ("Zware regen", "regen"),
    66: ("Lichte ijsregen", "regen"),
    67: ("IJsregen", "regen"),
    71: ("Lichte sneeuw", "sneeuw"),
    73: ("Sneeuw", "sneeuw"),
    75: ("Zware sneeuw", "sneeuw"),
    77: ("Sneeuwkorrels", "sneeuw"),
    80: ("Lichte buien", "buien"),
    81: ("Buien", "buien"),
    82: ("Zware buien", "buien"),
    85: ("Lichte sneeuwbuien", "sneeuw"),
    86: ("Sneeuwbuien", "sneeuw"),
    95: ("Onweer", "onweer"),
    96: ("Onweer met lichte hagel", "onweer"),
    99: ("Onweer met hagel", "onweer"),
}

DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]
DAGNAAM = {"ma": "Maandag", "di": "Dinsdag", "wo": "Woensdag", "do": "Donderdag",
           "vr": "Vrijdag", "za": "Zaterdag", "zo": "Zondag"}


def _wind_woord(km):
    """Gemiddelde wind (km/u) -> woord, volgens de schaal van Beaufort (KNMI)."""
    if km is None:
        return None
    if km >= 103:
        return "zeer zware storm"
    if km >= 89:
        return "zware storm"
    if km >= 75:
        return "storm"
    if km >= 62:
        return "stormachtige wind"
    if km >= 50:
        return "harde wind"
    if km >= 39:
        return "vrij krachtige wind"
    return None


def _stoot_woord(km):
    """Windstoten (km/u) -> woord."""
    if km is None:
        return None
    if km >= 100:
        return "zeer zware windstoten"
    if km >= 75:
        return "zware windstoten"
    if km >= 60:
        return "harde windstoten"
    return None


def verwachting(d, wanneer="Vandaag"):
    """Maak een uitgebreide, gewone-taal omschrijving van een dag, bijvoorbeeld:
    'Vandaag: storm met veel regen (25 mm) en zware windstoten tot 95 km/u.'
    Geeft (tekst, waarschuwing) terug; waarschuwing: 0 = rustig, 1 = let op, 2 = storm/onweer."""
    code = d.get("code")
    try:
        code = int(code) if code is not None else None
    except Exception:
        code = None
    wind, stoot = d.get("wind"), d.get("stoten")
    mm, kans = d.get("mm"), d.get("regen")
    tmax, tmin = d.get("max"), d.get("min")
    delen = []          # hoofdzin
    extra = []          # aanvullingen
    waarsch = 0

    ww = _wind_woord(wind)
    sw = _stoot_woord(stoot)
    # de kern: storm of het weertype
    if ww in ("storm", "zware storm", "zeer zware storm"):
        kern = ww
        waarsch = 2
    elif stoot is not None and stoot >= 90:
        kern = "kans op storm"
        waarsch = 2
    elif ww:
        kern = ww
        waarsch = max(waarsch, 1)
    else:
        kern = None

    # neerslag
    sneeuw = code in (71, 73, 75, 77, 85, 86)
    onweer = code in (95, 96, 99)
    regen = None
    if mm is not None and mm >= 20:
        regen = "veel sneeuw" if sneeuw else "veel regen"
    elif mm is not None and mm >= 8:
        regen = "flink wat sneeuw" if sneeuw else "flink wat regen"
    elif mm is not None and mm >= 1:
        regen = ("af en toe sneeuw" if sneeuw else
                 ("buien" if code in (80, 81, 82) else "af en toe regen"))
    elif kans is not None and kans >= 40:
        regen = "kans op een bui"
    if regen and mm is not None and mm >= 8:
        regen += " (%d mm)" % round(mm)

    if kern and regen:
        delen.append("%s met %s" % (kern, regen))
    elif kern:
        delen.append(kern)
    elif regen:
        delen.append(regen)
    else:
        oms, _ = beschrijf(code)
        delen.append(oms.lower() + " en droog" if code in (0, 1, 2, 3) else oms.lower())

    if sw:
        delen.append("%s tot %d km/u" % (sw, round(stoot)))
        waarsch = max(waarsch, 2 if stoot >= 75 else 1)
    if onweer:
        extra.append("kans op onweer" + (" met hagel" if code in (96, 99) else ""))
        waarsch = max(waarsch, 2)
    if tmin is not None and tmin <= 0:
        extra.append("kans op vorst en gladheid" if (mm or 0) >= 0.5 else "kans op vorst")
        waarsch = max(waarsch, 1)
    if tmax is not None and tmax >= 30:
        extra.append("tropisch warm")
        waarsch = max(waarsch, 1)
    elif tmax is not None and tmax >= 25:
        extra.append("zomers warm")

    zin = " en ".join(delen)
    zin = zin[0].upper() + zin[1:]
    tekst = "%s: %s." % (wanneer, zin[0].lower() + zin[1:])
    if extra:
        e = ", ".join(extra)
        tekst += " " + e[0].upper() + e[1:] + "."
    return tekst, waarsch


def beschrijf(code):
    """Geef (omschrijving, icoon-categorie) voor een WMO-code."""
    try:
        return WMO.get(int(code), ("Wisselend", "bewolkt"))
    except Exception:
        return ("Onbekend", "bewolkt")


def _get(url, params, timeout=10):
    """Via netwerk.haal: met certifi, zodat het ook op Android (https) werkt."""
    import netwerk
    q = url + "?" + urllib.parse.urlencode(params)
    return json.loads(netwerk.haal(q, tijd=timeout).decode("utf-8"))


def zoek_plaats(naam, aantal=8):
    """Zoek plaatsen op naam. Geeft een lijst met dicts terug:
    {naam, regio, land, lat, lon}."""
    naam = (naam or "").strip()
    if not naam:
        return []
    try:
        data = _get(GEO_URL, {"name": naam, "count": aantal, "language": "nl",
                              "format": "json"})
    except Exception:
        return []
    out = []
    for r in (data.get("results") or []):
        out.append({
            "naam": r.get("name", naam),
            "regio": r.get("admin1", "") or "",
            "land": r.get("country", "") or "",
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
        })
    return out


def haal_weer(lat, lon):
    """Haal huidig weer + 7-daagse + uurverwachting (24u) op.
    Geeft een dict terug, of None bij mislukken."""
    try:
        data = _get(FC_URL, {
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "forecast_days": 7, "forecast_minutely_15": 8,
            "minutely_15": "precipitation",
            "current": ",".join([
                "temperature_2m", "apparent_temperature", "relative_humidity_2m",
                "weather_code", "wind_speed_10m", "wind_direction_10m",
                "wind_gusts_10m", "is_day"]),
            "hourly": ",".join([
                "temperature_2m", "precipitation_probability", "weather_code"]),
            "daily": ",".join([
                "weather_code", "temperature_2m_max", "temperature_2m_min",
                "precipitation_probability_max", "sunrise", "sunset",
                "wind_speed_10m_max", "wind_gusts_10m_max", "precipitation_sum"]),
        })
    except Exception:
        return None

    cur = data.get("current") or {}
    oms, icoon = beschrijf(cur.get("weather_code"))
    huidig = {
        "temp": cur.get("temperature_2m"),
        "gevoel": cur.get("apparent_temperature"),
        "vocht": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"),
        "windricht": cur.get("wind_direction_10m"),
        "stoten": cur.get("wind_gusts_10m"),
        "dag": bool(cur.get("is_day", 1)),
        "oms": oms, "icoon": icoon,
    }

    # uurverwachting: vanaf nu, 24 uur vooruit
    hourly = data.get("hourly") or {}
    tijden = hourly.get("time") or []
    nu = (data.get("current") or {}).get("time", "")
    start = 0
    for i, t in enumerate(tijden):
        if t >= nu:
            start = i
            break
    uur = []
    temps = hourly.get("temperature_2m") or []
    regenk = hourly.get("precipitation_probability") or []
    codes = hourly.get("weather_code") or []
    for i in range(start, min(start + 24, len(tijden))):
        _, ic = beschrijf(codes[i] if i < len(codes) else 0)
        uur.append({
            "tijd": tijden[i][11:16],          # HH:MM
            "temp": temps[i] if i < len(temps) else None,
            "regen": regenk[i] if i < len(regenk) else None,
            "icoon": ic,
        })

    # 7-daagse
    daily = data.get("daily") or {}
    dtijden = daily.get("time") or []
    dmax = daily.get("temperature_2m_max") or []
    dmin = daily.get("temperature_2m_min") or []
    dcode = daily.get("weather_code") or []
    dregen = daily.get("precipitation_probability_max") or []
    dwind = daily.get("wind_speed_10m_max") or []
    dstoot = daily.get("wind_gusts_10m_max") or []
    dmm = daily.get("precipitation_sum") or []
    import datetime
    dagen = []
    for i, d in enumerate(dtijden):
        oms_d, ic_d = beschrijf(dcode[i] if i < len(dcode) else 0)
        try:
            wd = datetime.date.fromisoformat(d).weekday()
            label = DAGEN[wd]
        except Exception:
            label = d[5:]
        dagen.append({
            "datum": d, "dag": label,
            "max": dmax[i] if i < len(dmax) else None,
            "min": dmin[i] if i < len(dmin) else None,
            "regen": dregen[i] if i < len(dregen) else None,
            "oms": oms_d, "icoon": ic_d,
            "code": dcode[i] if i < len(dcode) else None,
            "wind": dwind[i] if i < len(dwind) else None,
            "stoten": dstoot[i] if i < len(dstoot) else None,
            "mm": dmm[i] if i < len(dmm) else None,
        })
    for i, d in enumerate(dagen):
        wanneer = "Vandaag" if i == 0 else ("Morgen" if i == 1 else DAGNAAM.get(d["dag"], d["dag"]))
        d["tekst"], d["waarschuwing"] = verwachting(d, wanneer)

    zon = daily.get("sunrise") or []
    onder = daily.get("sunset") or []
    huidig["op"] = zon[0][11:16] if zon else ""
    huidig["onder"] = onder[0][11:16] if onder else ""

    # regen per kwartier, de komende 2 uur (voor de buienradar-grafiek)
    m15 = data.get("minutely_15") or {}
    kwartier = [{"tijd": t[11:16], "mm": v or 0.0} for t, v in zip(m15.get("time") or [], m15.get("precipitation") or [])]
    return {"huidig": huidig, "uur": uur, "dagen": dagen, "kwartier": kwartier[:8]}


if __name__ == "__main__":
    # snelle test vanaf de opdrachtregel
    plaatsen = zoek_plaats("Breda")
    print("Gevonden:", [p["naam"] + ", " + p["land"] for p in plaatsen[:3]])
    if plaatsen:
        p = plaatsen[0]
        w = haal_weer(p["lat"], p["lon"])
        h = w["huidig"]
        print("Nu in %s: %s graden, %s, wind %s km/u" %
              (p["naam"], round(h["temp"]), h["oms"], round(h["wind"])))
        print("Morgen:", w["dagen"][1])
        print("Eerste uur:", w["uur"][0])
        for d in w["dagen"]:
            print(d["tekst"])
