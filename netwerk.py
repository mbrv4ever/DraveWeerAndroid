# -*- coding: utf-8 -*-
# DraveNavi - Copyright (C) 2026 Dravenlock (Roger & Claudio).
"""netwerk.py - kaarttegels, adressen zoeken en routes (openrouteservice), alles in achtergronddraden."""
import io
import json
import os
import queue
import ssl
import threading
import time
import urllib.parse
import urllib.request

from geo import Route

AGENT = "DraveNavi/0.1 (Dravenlock; persoonlijk gebruik)"
ORS = "https://api.openrouteservice.org"
PROFIEL = {"lopen": "foot-walking", "fietsen": "cycling-regular", "auto": "driving-car"}
KAART_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"     # donker maken doet de app zelf
BRON = "Kaart: OpenStreetMap  |  Route: openrouteservice"


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL = _context()


def haal(url, data=None, kop=None, tijd=15):
    k = {"User-Agent": AGENT}
    if kop:
        k.update(kop)
    req = urllib.request.Request(url, data=data, headers=k)
    with urllib.request.urlopen(req, timeout=tijd, context=SSL) as r:
        return r.read()


class Tegels:
    """Kaarttegels: eerst uit de cache op schijf, anders downloaden (4 draden)."""

    def __init__(self, map_, stijl="donker"):
        self.map = map_
        self.stijl = stijl
        self.klaar = {}          # (stijl, z, x, y) -> bytes (de pygame-kant maakt er een plaatje van)
        self.bezig = set()
        self.wacht = queue.LifoQueue()
        self.fout = 0
        for _ in range(4):
            threading.Thread(target=self._werk, daemon=True).start()

    def pad(self, s, z, x, y):
        return os.path.join(self.map, s, str(z), str(x), "%d.png" % y)

    def vraag(self, z, x, y):
        sleutel = ("osm", z, x, y)
        if sleutel in self.bezig or sleutel in self.klaar:
            return
        self.bezig.add(sleutel)
        self.wacht.put(sleutel)

    def _werk(self):
        while True:
            s, z, x, y = self.wacht.get()
            p = self.pad(s, z, x, y)
            data = None
            try:
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        data = f.read()
                else:
                    url = KAART_URL.format(z=z, x=x, y=y)
                    data = haal(url, tijd=10)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "wb") as f:
                        f.write(data)
                self.fout = 0
            except Exception:
                self.fout += 1
                time.sleep(0.5)
            self.klaar[(s, z, x, y)] = data
            self.bezig.discard((s, z, x, y))


class Planner:
    """Adressen zoeken en routes berekenen bij openrouteservice (in een achtergronddraad)."""

    def __init__(self, sleutel):
        self.sleutel = (sleutel or "").strip()
        self.antwoord = queue.Queue()     # (soort, resultaat)

    def heeft_sleutel(self):
        return len(self.sleutel) > 20

    def zoek(self, tekst, bij=None):
        doel = self._zoek if self.heeft_sleutel() else self._zoek_osm
        threading.Thread(target=doel, args=(tekst, bij), daemon=True).start()

    def _zoek_osm(self, tekst, bij):
        """Reserve zonder sleutel: Nominatim (OpenStreetMap)."""
        try:
            p = {"q": tekst, "format": "jsonv2", "countrycodes": "nl,be,de", "limit": "8", "accept-language": "nl"}
            if bij:
                p["viewbox"] = "%.4f,%.4f,%.4f,%.4f" % (bij[1] - 0.6, bij[0] + 0.4, bij[1] + 0.6, bij[0] - 0.4)
            d = json.loads(haal("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(p)))
            self.antwoord.put(("zoek", [dict(naam=r.get("display_name", "?"), lat=float(r["lat"]), lon=float(r["lon"]))
                                        for r in d]))
        except Exception as e:
            self.antwoord.put(("fout", "zoeken: %s" % e))

    def _zoek(self, tekst, bij):
        try:
            p = {"api_key": self.sleutel, "text": tekst, "boundary.country": "NL,BE,DE", "size": "8", "lang": "nl"}
            if bij:
                p["focus.point.lat"], p["focus.point.lon"] = "%.5f" % bij[0], "%.5f" % bij[1]
            d = json.loads(haal(ORS + "/geocode/search?" + urllib.parse.urlencode(p)))
            uit = []
            for f in d.get("features", []):
                lon, lat = f["geometry"]["coordinates"][:2]
                pr = f.get("properties", {})
                uit.append(dict(naam=pr.get("label") or pr.get("name") or "?", lat=lat, lon=lon))
            self.antwoord.put(("zoek", uit))
        except Exception as e:
            self.antwoord.put(("fout", "zoeken: %s" % e))

    def route(self, van, naar, vervoer, vermijd=None):
        if self.heeft_sleutel():
            threading.Thread(target=self._route, args=(van, naar, vervoer, vermijd), daemon=True).start()
        else:
            threading.Thread(target=self._route_osrm, args=(van, naar, vervoer), daemon=True).start()

    def _route_osrm(self, van, naar, vervoer):
        """Reserve zonder sleutel: de openbare OSRM-testserver (alleen auto)."""
        try:
            url = ("https://router.project-osrm.org/route/v1/driving/%.6f,%.6f;%.6f,%.6f"
                   "?overview=full&geometries=geojson&steps=true" % (van[1], van[0], naar[1], naar[0]))
            d = json.loads(haal(url, tijd=20))
            r = d["routes"][0]
            punten = [(c[1], c[0]) for c in r["geometry"]["coordinates"]]
            stappen = []
            for leg in r.get("legs", []):
                for st in leg.get("steps", []):
                    m = st.get("maneuver", {})
                    loc = m.get("location", [0, 0])
                    stappen.append(dict(soort=osrm_soort(m), tekst="", naam=st.get("name", "") or "",
                                        start=dichtste(punten, (loc[1], loc[0])), afslag=m.get("exit"),
                                        afstand=st.get("distance", 0)))
            self.antwoord.put(("route", Route(punten, stappen, r.get("distance", 0), r.get("duration", 0), "auto")))
        except Exception as e:
            self.antwoord.put(("fout", "route: %s" % e))

    def _route(self, van, naar, vervoer, vermijd=None):
        try:
            prof = PROFIEL[vervoer]
            verzoek = {"coordinates": [[van[1], van[0]], [naar[1], naar[0]]], "language": "nl",
                       "instructions": True, "units": "m"}
            if vermijd:
                verzoek["options"] = {"avoid_polygons": vermijd}
            body = json.dumps(verzoek).encode()
            d = json.loads(haal("%s/v2/directions/%s/geojson" % (ORS, prof), data=body,
                                kop={"Authorization": self.sleutel, "Content-Type": "application/json",
                                     "Accept": "application/geo+json"}, tijd=20))
            self.antwoord.put(("route", lees_route(d, vervoer)))
        except Exception as e:
            self.antwoord.put(("fout", "route: %s" % e))


def dichtste(punten, p):
    beste, bi = 1e18, 0
    for i, q in enumerate(punten):
        d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
        if d < beste:
            beste, bi = d, i
    return bi


def osrm_soort(m):
    """OSRM-afslag -> dezelfde codes als openrouteservice (0 links, 1 rechts, ... 7 rotonde, 10 aankomst, 11 vertrek)."""
    t, mod = m.get("type", ""), m.get("modifier", "straight")
    if t == "depart":
        return 11
    if t == "arrive":
        return 10
    if t in ("roundabout", "rotary"):
        return 7
    if t == "exit roundabout":
        return 8
    if t == "fork" or t == "merge":
        return 12 if "left" in mod else 13 if "right" in mod else 6
    return {"left": 0, "right": 1, "sharp left": 2, "sharp right": 3, "slight left": 4, "slight right": 5,
            "straight": 6, "uturn": 9}.get(mod, 6)


def lees_route(d, vervoer):
    f = d["features"][0]
    punten = [(c[1], c[0]) for c in f["geometry"]["coordinates"]]
    pr = f["properties"]
    stappen = []
    for seg in pr.get("segments", []):
        for st in seg.get("steps", []):
            stappen.append(dict(soort=st.get("type", 6), tekst=st.get("instruction", ""), naam=st.get("name", "") or "",
                                start=st.get("way_points", [0, 0])[0], afslag=st.get("exit_number"),
                                afstand=st.get("distance", 0)))
    som = pr.get("summary", {})
    return Route(punten, stappen, som.get("distance", 0), som.get("duration", 0), vervoer)
