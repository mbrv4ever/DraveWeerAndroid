# -*- coding: utf-8 -*-
# DraveNavi - Copyright (C) 2026 Dravenlock (Roger & Claudio).
"""geo.py - rekenwerk met de aarde: kaartpixels (Web Mercator), afstanden en de plek op een route."""
import math

TEGEL = 256
R_AARDE = 6371000.0


def naar_pixel(lat, lon, zoom):
    """Breedte/lengte -> wereldpixels op dit zoomniveau."""
    n = TEGEL * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def van_pixel(x, y, zoom):
    n = TEGEL * (2 ** zoom)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def afstand(a, b):
    """Afstand in meter tussen (lat, lon) en (lat, lon)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_AARDE * math.asin(min(1.0, math.sqrt(d)))


def koers(a, b):
    """Kompasrichting (0 = noord, 90 = oost) van a naar b."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _lokaal(p, ref):
    """(lat, lon) -> meters (x oost, y noord) rond ref; prima voor korte stukjes."""
    kx = math.cos(math.radians(ref[0])) * math.pi / 180 * R_AARDE
    ky = math.pi / 180 * R_AARDE
    return (p[1] - ref[1]) * kx, (p[0] - ref[0]) * ky


def op_lijn(p, a, b):
    """Dichtstbijzijnde punt op stuk a-b: (afstand in m, fractie 0..1)."""
    ax, ay = _lokaal(a, p)
    bx, by = _lokaal(b, p)
    dx, dy = bx - ax, by - ay
    lengte2 = dx * dx + dy * dy
    t = 0.0 if lengte2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / lengte2))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(qx, qy), t


class Route:
    """Een berekende route: punten, afslagen, en waar je nu op de route bent."""

    def __init__(self, punten, stappen, totaal_m, totaal_s, profiel):
        self.punten = punten              # [(lat, lon), ...]
        self.stappen = stappen            # [dict(soort, tekst, naam, start, afslag, afstand)]
        self.totaal_m = totaal_m
        self.totaal_s = totaal_s
        self.profiel = profiel
        self.cum = [0.0]                  # afstand vanaf het begin tot elk punt
        for i in range(1, len(punten)):
            self.cum.append(self.cum[-1] + afstand(punten[i - 1], punten[i]))
        self.index = 0                    # op welk stukje je zit (voor sneller zoeken)

    def plek(self, p):
        """Waar ben je? -> (afstand tot de route in m, afgelegde meters langs de route)."""
        beste = (1e12, 0.0, 0)
        lo = max(0, self.index - 30)
        hi = min(len(self.punten) - 1, self.index + 200)
        for zoek in ((lo, hi), (0, len(self.punten) - 1)):
            for i in range(zoek[0], zoek[1]):
                d, t = op_lijn(p, self.punten[i], self.punten[i + 1])
                if d < beste[0]:
                    langs = self.cum[i] + t * (self.cum[i + 1] - self.cum[i])
                    beste = (d, langs, i)
            if beste[0] < 60:
                break
        self.index = beste[2]
        return beste[0], beste[1]

    def volgende_stap(self, langs):
        """De eerstvolgende afslag na deze plek -> (stap, meters ernaartoe) of (None, rest)."""
        for st in self.stappen:
            m = self.cum[min(st["start"], len(self.cum) - 1)]
            if m > langs + 3 and st["soort"] not in (6, 8, 11):
                return st, m - langs
        return None, self.totaal_m - langs

    def rest(self, langs):
        return max(0.0, self.cum[-1] - langs)
