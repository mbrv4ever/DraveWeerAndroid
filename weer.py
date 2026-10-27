# -*- coding: utf-8 -*-
# DraveWeer voor Android - Copyright (C) 2026 Dravenlock (Roger & Claudio).
"""weer.py - DraveWeer op de telefoon: groot, duidelijk, met buienradar en Leon die het weer voorleest.

Weer: Open-Meteo (gratis, geen sleutel). Radar: RainViewer (gratis, tot zoom 7). Kaart: OpenStreetMap.
"""
import io
import json
import math
import os
import queue
import threading
import time

import pygame

import geo
import gps as gpsmod
import netwerk
import weer_engine as we

VERSIE = "0.3"
ANDROID = gpsmod.ANDROID
HIER = os.path.dirname(os.path.abspath(__file__))

ZWART = (10, 8, 16)
PANEEL = (24, 18, 38)
PAARS = (150, 90, 230)
PAARS_D = (70, 40, 120)
ZILVER = (226, 226, 236)
GRIJS = (150, 146, 166)
GEEL = (255, 222, 60)
ROOD = (225, 60, 60)
ORANJE = (255, 150, 30)
BLAUW = (90, 160, 255)
WIT = (250, 250, 255)

RICHTING = ["noord", "noordoost", "oost", "zuidoost", "zuid", "zuidwest", "west", "noordwest"]
RADAR_API = "https://api.rainviewer.com/public/weather-maps.json"


def data_map():
    basis = (os.environ.get("ANDROID_PRIVATE") or HIER) if ANDROID else HIER
    p = os.path.join(basis, "DraveWeer-data")
    os.makedirs(p, exist_ok=True)
    return p


def beaufort(kmu):
    grenzen = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
    for i, g in enumerate(grenzen):
        if (kmu or 0) < g:
            return i
    return 12


class Stem:
    """Leon: vaste zinnetjes achter elkaar afspelen, met een kleine pauze ertussen."""

    def __init__(self):
        self.clips, self.rij, self.kanaal, self.vrij = {}, [], None, 0
        try:
            pygame.mixer.init(22050, -16, 1, 1024)
            m = os.path.join(HIER, "stem_weer")
            for f in os.listdir(m):
                if f.endswith(".wav"):
                    self.clips[f[:-4]] = pygame.mixer.Sound(os.path.join(m, f))
        except Exception:
            self.clips = {}

    def zeg(self, delen):
        self.stil()
        self.rij = [d for d in delen if d in self.clips]

    def stil(self):
        self.rij = []
        if self.kanaal:
            self.kanaal.stop()

    def bezig(self):
        return bool(self.rij) or (self.kanaal is not None and self.kanaal.get_busy())

    def update(self):
        nu = time.time()
        if self.kanaal is not None and self.kanaal.get_busy():
            self.vrij = nu + 0.12
            return
        if self.rij and nu >= self.vrij:
            self.kanaal = self.clips[self.rij.pop(0)].play()
            self.vrij = nu + 0.3


def getal_clips(t):
    """Temperatuur -> ['min', 'n5'] of ['n14']."""
    n = int(round(t or 0))
    uit = ["min"] if n < 0 else []
    return uit + ["n%d" % min(40, abs(n))]


def minuten_clip(m):
    return "m%d" % min((15, 30, 45, 60, 90, 120), key=lambda x: abs(x - m))


def voorlees_zinnen(w):
    """Het weerbericht als rijtje Leon-zinnetjes."""
    h, d0 = w["huidig"], w["dagen"][0] if w["dagen"] else {}
    uit = ["het_is_nu"] + getal_clips(h.get("temp")) + ["graden_en", "c_" + h.get("icoon", "bewolkt")]
    if d0:
        uit += ["vandaag_max"] + getal_clips(d0.get("max")) + ["graden"]
    # regen de komende 2 uur
    kw = w.get("kwartier") or []
    nat = [k["mm"] >= 0.1 for k in kw]
    if nat and nat[0]:
        uit.append("regent_nu")
        if False in nat:
            uit += ["stopt_over", minuten_clip(15 * nat.index(False))]
    elif True in nat:
        uit += ["regen_over", minuten_clip(15 * nat.index(True)), "gaat_regenen"]
    elif kw:
        uit.append("droog_2u")
    ww = we._wind_woord(h.get("wind"))
    if ww:
        uit.append("w_" + ww.replace(" ", "_"))
    elif (h.get("stoten") or 0) >= 75:
        uit.append("let_stoten")
    if d0:
        if d0.get("code") in (95, 96, 99):
            uit.append("let_onweer")
        if (d0.get("min") or 99) <= 0:
            uit.append("let_vorst")
        if (d0.get("max") or 0) >= 30:
            uit.append("let_tropisch")
    if len(w["dagen"]) > 1:
        d1 = w["dagen"][1]
        uit += ["morgen", "c_" + d1.get("icoon", "bewolkt"), "max"] + getal_clips(d1.get("max")) + ["graden"]
    return uit


# ------------------------------------------------------------------ weerplaatjes (zelf getekend)
def teken_icoon(s, soort, r, dag=True):
    cx, cy, g = r.centerx, r.centery, min(r.w, r.h)

    def zon(x, y, straal):
        for i in range(12):
            a = i * math.pi / 6
            pygame.draw.line(s, GEEL, (x + math.cos(a) * straal * 1.25, y + math.sin(a) * straal * 1.25),
                             (x + math.cos(a) * straal * 1.6, y + math.sin(a) * straal * 1.6), max(3, int(straal * 0.16)))
        pygame.draw.circle(s, GEEL, (int(x), int(y)), int(straal))

    def maan(x, y, straal):
        pygame.draw.circle(s, (230, 230, 210), (int(x), int(y)), int(straal))
        pygame.draw.circle(s, ZWART, (int(x + straal * 0.45), int(y - straal * 0.25)), int(straal * 0.9))

    def wolk(x, y, b, kl=(210, 214, 228)):
        rand = tuple(max(0, c - 70) for c in kl)
        for (dx, dy, rr) in ((-0.28, 0.05, 0.24), (0.0, -0.12, 0.32), (0.3, 0.06, 0.22)):
            pygame.draw.circle(s, rand, (int(x + dx * b), int(y + dy * b)), int(rr * b) + 3)
        pygame.draw.rect(s, rand, (x - b * 0.5 - 3, y + 0.02 * b - 3, b + 6, b * 0.24 + 6), border_radius=int(b * 0.12))
        for (dx, dy, rr) in ((-0.28, 0.05, 0.24), (0.0, -0.12, 0.32), (0.3, 0.06, 0.22)):
            pygame.draw.circle(s, kl, (int(x + dx * b), int(y + dy * b)), int(rr * b))
        pygame.draw.rect(s, kl, (x - b * 0.5, y + 0.02 * b, b, b * 0.24), border_radius=int(b * 0.12))

    def druppels(x, y, b, kl=BLAUW, n=3, lang=0.22):
        for i in range(n):
            dx = (i - (n - 1) / 2) * b * 0.26
            pygame.draw.line(s, kl, (x + dx, y), (x + dx - b * 0.07, y + b * lang), max(3, int(b * 0.07)))

    if soort == "zon":
        (zon if dag else maan)(cx, cy, g * 0.28)
    elif soort == "halfbewolkt":
        (zon if dag else maan)(cx - g * 0.12, cy - g * 0.14, g * 0.2)
        wolk(cx + g * 0.06, cy + g * 0.08, g * 0.62)
    elif soort == "bewolkt":
        wolk(cx - g * 0.12, cy - g * 0.1, g * 0.5, (160, 164, 180))
        wolk(cx + g * 0.06, cy + g * 0.06, g * 0.7)
    elif soort == "mist":
        wolk(cx, cy - g * 0.12, g * 0.62, (170, 174, 186))
        for i in range(3):
            pygame.draw.line(s, (190, 194, 206), (cx - g * 0.38 + i * 8, cy + g * (0.18 + i * 0.1)),
                             (cx + g * 0.34 - i * 8, cy + g * (0.18 + i * 0.1)), max(3, int(g * 0.05)))
    elif soort in ("motregen", "regen", "buien"):
        if soort == "buien":
            (zon if dag else maan)(cx - g * 0.16, cy - g * 0.2, g * 0.16)
        wolk(cx, cy - g * 0.1, g * 0.7, (150, 156, 176) if soort == "regen" else (190, 194, 210))
        druppels(cx, cy + g * 0.16, g, n=2 if soort == "motregen" else 3, lang=0.12 if soort == "motregen" else 0.22)
    elif soort == "sneeuw":
        wolk(cx, cy - g * 0.1, g * 0.7)
        for i in range(3):
            x, y = cx + (i - 1) * g * 0.24, cy + g * 0.26
            for a in range(3):
                h = a * math.pi / 3
                pygame.draw.line(s, WIT, (x - math.cos(h) * g * 0.07, y - math.sin(h) * g * 0.07),
                                 (x + math.cos(h) * g * 0.07, y + math.sin(h) * g * 0.07), 3)
    elif soort == "onweer":
        wolk(cx, cy - g * 0.12, g * 0.72, (120, 124, 146))
        pygame.draw.polygon(s, GEEL, [(cx + g * 0.02, cy + g * 0.02), (cx - g * 0.12, cy + g * 0.26), (cx, cy + g * 0.24),
                                      (cx - g * 0.08, cy + g * 0.44), (cx + g * 0.14, cy + g * 0.16), (cx + g * 0.02, cy + g * 0.18)])
    else:
        wolk(cx, cy, g * 0.7)


class Radar:
    """RainViewer: de radarbeelden van de afgelopen 2 uur (tot zoom 7)."""

    def __init__(self):
        self.host, self.beelden, self.tijd, self.klaar = "", [], 0, {}
        self.bezig, self.wacht = set(), queue.Queue()
        for _ in range(3):
            threading.Thread(target=self._werk, daemon=True).start()

    def ververs(self):
        if time.time() - self.tijd < 300:
            return
        self.tijd = time.time()
        threading.Thread(target=self._lijst, daemon=True).start()

    def _lijst(self):
        try:
            d = json.loads(netwerk.haal(RADAR_API, tijd=15))
            self.host = d.get("host", "https://tilecache.rainviewer.com")
            self.beelden = [(b["time"], b["path"]) for b in d.get("radar", {}).get("past", [])]
        except Exception:
            self.tijd = time.time() - 240

    def vraag(self, pad, z, x, y):
        k = (pad, z, x, y)
        if k in self.klaar or k in self.bezig:
            return
        self.bezig.add(k)
        self.wacht.put(k)

    def _werk(self):
        while True:
            pad, z, x, y = k = self.wacht.get()
            try:
                self.klaar[k] = netwerk.haal("%s%s/256/%d/%d/%d/2/1_1.png" % (self.host, pad, z, x, y), tijd=15)
            except Exception:
                self.klaar[k] = None
            self.bezig.discard(k)


class Weer:
    def __init__(self):
        pygame.init()
        self.data = data_map()
        self.inst = {"plaats": None, "recent": []}
        try:
            with open(os.path.join(self.data, "instellingen.json"), encoding="utf-8") as f:
                self.inst.update(json.load(f))
        except Exception:
            pass
        if ANDROID:
            info = pygame.display.Info()
            pw, ph = max(1, info.current_w), max(1, info.current_h)
            self.W, self.H = 540, int(540 * max(pw, ph) / min(pw, ph))
            self.venster = pygame.display.set_mode((self.W, self.H), pygame.FULLSCREEN | pygame.SCALED)
        else:
            self.W, self.H = 540, 1040
            self.venster = pygame.display.set_mode((self.W, self.H))
        pygame.display.set_caption("DraveWeer")
        fb = os.path.join(HIER, "assets", "DejaVuSans-Bold.ttf")
        fr = os.path.join(HIER, "assets", "DejaVuSans.ttf")
        self.f_temp = pygame.font.Font(fb, 120)
        self.f_reus = pygame.font.Font(fb, 56)
        self.f_groot = pygame.font.Font(fb, 38)
        self.f = pygame.font.Font(fb, 28)
        self.f_mid = pygame.font.Font(fb, 23)
        self.f_klein = pygame.font.Font(fr, 21)
        self.f_mini = pygame.font.Font(fr, 15)
        self.klok = pygame.time.Clock()
        self.stem = Stem()
        self.gps = gpsmod.Gps()
        self.tegels = netwerk.Tegels(os.path.join(self.data, "tegels"), "licht")
        self.radar = Radar()
        self.plaatjes = {}
        self.antwoord = queue.Queue()
        self.weer = None
        self.weer_tijd = 0
        self.bezig = None
        self.melding = None
        self.scherm = "nu"
        self.scroll = 0
        self.knoppen = []
        self.zoektekst, self.resultaten = "", []
        self.plaatsnaam = (self.inst.get("plaats") or {}).get("naam") or "Mijn plek"
        self.radar_i, self.radar_t, self.radar_speel = 0, 0.0, True
        self.radar_zoom = 7
        self.tijd = 0.0
        self.stop = False
        self.sleep = None
        if not self.inst.get("plaats"):
            self.gps.start()

    # ------------------------------------------------------------ gegevens
    def plek(self):
        p = self.inst.get("plaats")
        if p:
            return (p["lat"], p["lon"])
        return self.gps.plek

    def bewaar(self):
        try:
            with open(os.path.join(self.data, "instellingen.json"), "w", encoding="utf-8") as f:
                json.dump(self.inst, f)
        except Exception:
            pass

    def haal(self, nu=False):
        p = self.plek()
        if not p or self.bezig == "laden":
            return
        if not nu and time.time() - self.weer_tijd < 600:
            return
        self.weer_tijd = time.time()
        self.bezig = "laden" if not self.weer else None
        threading.Thread(target=self._haal, args=(p,), daemon=True).start()
        if not self.inst.get("plaats") and self.plaatsnaam == "Mijn plek":
            threading.Thread(target=self._naam_van_plek, args=(p,), daemon=True).start()

    def _haal(self, p):
        w = we.haal_weer(p[0], p[1])
        self.antwoord.put(("weer", w))

    def _naam_van_plek(self, p):
        try:
            d = json.loads(netwerk.haal("https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=10&accept-language=nl"
                                        "&lat=%.4f&lon=%.4f" % p, tijd=10))
            a = d.get("address", {})
            naam = a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
            if naam:
                self.antwoord.put(("naam", naam))
        except Exception:
            pass

    def zoek(self):
        t = self.zoektekst.strip()
        if len(t) < 2:
            return
        try:
            pygame.key.stop_text_input()
        except Exception:
            pass
        self.bezig = "zoeken"
        threading.Thread(target=lambda: self.antwoord.put(("zoek", we.zoek_plaats(t))), daemon=True).start()

    def kies_plaats(self, r):
        if r is None:
            self.inst["plaats"] = None
            self.plaatsnaam = "Mijn plek"
            self.gps.start()
        else:
            self.inst["plaats"] = dict(naam=r["naam"], lat=r["lat"], lon=r["lon"])
            self.plaatsnaam = r["naam"]
            rec = [x for x in self.inst.get("recent", []) if x.get("naam") != r["naam"]]
            self.inst["recent"] = [self.inst["plaats"]] + rec[:5]
        self.bewaar()
        self.weer = None
        self.weer_tijd = 0
        self.scherm = "nu"
        self.haal(nu=True)

    def verwerk(self):
        try:
            while True:
                soort, res = self.antwoord.get_nowait()
                if soort == "weer":
                    self.bezig = None
                    if res:
                        self.weer = res
                        self.weer_tijd = time.time()
                    else:
                        self.melding = ("Geen weer ontvangen. Is er internet?", time.time() + 4)
                        self.weer_tijd = time.time() - 540
                elif soort == "naam":
                    self.plaatsnaam = res
                elif soort == "zoek":
                    self.bezig = None
                    self.resultaten = res
                    if not res:
                        self.melding = ("Niets gevonden.", time.time() + 3)
        except queue.Empty:
            pass

    # ------------------------------------------------------------ tekenhulp
    def tekst(self, t, font, kleur, x, y, midden=False, rechts=False, max_b=None):
        if max_b:
            while font.size(t)[0] > max_b and len(t) > 3:
                t = t[:-4] + "..."
        img = font.render(t, True, kleur)
        r = img.get_rect()
        if midden:
            r.midtop = (x, y)
        elif rechts:
            r.topright = (x, y)
        else:
            r.topleft = (x, y)
        self.venster.blit(img, r)
        return r

    def breek(self, tekst, font, breed):
        regels, nu = [], ""
        for w in tekst.split():
            if font.size((nu + " " + w).strip())[0] <= breed:
                nu = (nu + " " + w).strip()
            else:
                regels.append(nu)
                nu = w
        if nu:
            regels.append(nu)
        return regels or [""]

    def knop(self, rect, label, actie, kleur=PAARS_D, rand=PAARS, font=None, tekstkleur=ZILVER):
        r = pygame.Rect(rect)
        pygame.draw.rect(self.venster, kleur, r, border_radius=14)
        pygame.draw.rect(self.venster, rand, r, 3, border_radius=14)
        if label:
            img = (font or self.f).render(label, True, tekstkleur)
            self.venster.blit(img, img.get_rect(center=r.center))
        self.knoppen.append((r, actie))
        return r

    @staticmethod
    def graden(t):
        return "-" if t is None else "%d°" % round(t)

    def onderbalk(self):
        H, W = self.H, self.W
        pygame.draw.rect(self.venster, PANEEL, (0, H - 112, W, 112))
        pygame.draw.line(self.venster, PAARS, (0, H - 112), (W, H - 112), 3)
        bw = (W - 16 * 2 - 3 * 10) // 4
        for i, (sl, label) in enumerate((("nu", "Nu"), ("uren", "Uren"), ("week", "Week"), ("radar", "Radar"))):
            gekozen = self.scherm == sl
            self.knop((16 + i * (bw + 10), H - 96, bw, 80), label, lambda s=sl: self.naar(s),
                      kleur=PAARS if gekozen else PANEEL, rand=GEEL if gekozen else PAARS,
                      tekstkleur=ZWART if gekozen else ZILVER)

    def naar(self, s):
        self.scherm = s
        self.scroll = 0
        if s == "radar":
            self.radar.ververs()
        if s != "zoek":
            try:
                pygame.key.stop_text_input()
            except Exception:
                pass

    # ------------------------------------------------------------ schermen
    def bovenbalk(self):
        W = self.W
        self.tekst(self.plaatsnaam, self.f_groot, ZILVER, 18, 22, max_b=W - 280)
        self.knop((W - 166, 14, 150, 66), "Plaats", lambda: self.naar_zoek(), kleur=PANEEL)
        r = self.knop((W - 252, 14, 76, 66), "", self.vernieuw, kleur=PANEEL, rand=GEEL)
        # pijltje in een rondje (vernieuwen)
        draai = (self.tijd * 6) if self.bezig == "laden" or self.weer_tijd > time.time() - 1.2 else 0
        a0 = -0.6 + draai
        pygame.draw.arc(self.venster, GEEL, (r.centerx - 20, r.centery - 20, 40, 40), a0, a0 + 4.8, 5)
        hx, hy = r.centerx + 20 * math.cos(a0), r.centery - 20 * math.sin(a0)
        pygame.draw.polygon(self.venster, GEEL, [(hx - 9, hy - 3), (hx + 9, hy - 3), (hx, hy + 9)])

    def vernieuw(self):
        self.haal(nu=True)
        self.radar.tijd = 0
        self.radar.ververs()
        self.melding = ("Het weer wordt vernieuwd...", time.time() + 1.5)

    def naar_zoek(self):
        self.naar("zoek")
        self.resultaten = []
        try:
            pygame.key.start_text_input()
        except Exception:
            pass

    def scherm_nu(self):
        v, W, H = self.venster, self.W, self.H
        self.bovenbalk()
        w = self.weer
        if not w:
            t = "GPS zoeken..." if not self.plek() else "Het weer wordt opgehaald..."
            if self.gps.status == "geen_toestemming" and not self.inst.get("plaats"):
                t = "Geen toestemming voor je plek. Kies een plaats."
            for i, r in enumerate(self.breek(t, self.f, W - 60)):
                self.tekst(r, self.f, GRIJS, W // 2, 300 + i * 40, midden=True)
            return
        h = w["huidig"]
        d0 = w["dagen"][0] if w["dagen"] else {}
        y = 96
        if d0.get("waarschuwing"):
            kl = ROOD if d0["waarschuwing"] >= 2 else ORANJE
            regels = self.breek(d0.get("tekst", ""), self.f_mid, W - 70)[:3]
            r = pygame.Rect(14, y, W - 28, 20 + 30 * len(regels))
            pygame.draw.rect(v, ZWART, r, border_radius=12)
            pygame.draw.rect(v, kl, r, 4, border_radius=12)
            for i, t in enumerate(regels):
                self.tekst(t, self.f_mid, kl if i == 0 else ZILVER, r.x + 16, r.y + 10 + i * 30)
            y = r.bottom + 10
        teken_icoon(v, h.get("icoon", "bewolkt"), pygame.Rect(10, y, 230, 230), h.get("dag", True))
        self.tekst(self.graden(h.get("temp")), self.f_temp, WIT, W - 20, y + 4, rechts=True)
        self.tekst(h.get("oms", ""), self.f, GEEL, W - 20, y + 150, rechts=True, max_b=280)
        self.tekst("Voelt als " + self.graden(h.get("gevoel")), self.f_klein, ZILVER, W - 20, y + 190, rechts=True)
        y += 250
        richt = RICHTING[int(((h.get("windricht") or 0) + 22.5) // 45) % 8]
        regels = [("Wind", "%s %d Bft" % (richt.capitalize(), beaufort(h.get("wind")))),
                  ("Vocht", "%d%%" % round(h.get("vocht") or 0)),
                  ("Zon", "op %s, onder %s" % (h.get("op", ""), h.get("onder", "")))]
        for k, t in regels:
            self.tekst(k, self.f, PAARS, 20, y)
            self.tekst(t, self.f, ZILVER, 150, y, max_b=W - 170)
            y += 42
        y += 8
        y = self.regengrafiek(pygame.Rect(14, y, W - 28, 200))
        if d0:
            self.tekst("Vandaag  %s / %s" % (self.graden(d0.get("max")), self.graden(d0.get("min"))), self.f, ZILVER, 20, y + 12)
        self.tekst("Bijgewerkt %s" % time.strftime("%H:%M", time.localtime(self.weer_tijd)), self.f_mini, GRIJS, W - 20,
                   self.H - 140, rechts=True)
        # Leon
        self.knop((W - 200, y + 4, 184, 60), "Stop" if self.stem.bezig() else "Lees voor",
                  lambda: self.stem.stil() if self.stem.bezig() else self.stem.zeg(voorlees_zinnen(self.weer)),
                  kleur=PAARS if not self.stem.bezig() else ROOD, rand=GEEL, tekstkleur=ZWART)
        self.onderbalk()

    def regengrafiek(self, r):
        """Buienradar voor jouw plek: regen per kwartier, de komende 2 uur."""
        v = self.venster
        kw = (self.weer or {}).get("kwartier") or []
        pygame.draw.rect(v, PANEEL, r, border_radius=14)
        nat = [k["mm"] >= 0.1 for k in kw]
        if not kw:
            t = "Regen: geen gegevens"
        elif nat[0]:
            t = "Het regent nu" + ("" if False not in nat else ", droog over %d min" % (15 * nat.index(False)))
        elif True in nat:
            t = "Regen over %d min" % (15 * nat.index(True))
        else:
            t = "Droog de komende 2 uur"
        self.tekst(t, self.f, BLAUW if True in nat else ZILVER, r.x + 16, r.y + 10, max_b=r.w - 30)
        if kw:
            onder, hoogte = r.bottom - 34, r.h - 82
            bw = (r.w - 32) / len(kw)
            pygame.draw.line(v, GRIJS, (r.x + 16, onder), (r.right - 16, onder), 2)
            for i, k in enumerate(kw):
                mm = min(4.0, k["mm"] * 4)              # mm per kwartier -> mm per uur, tot 4 mm/u vol
                hh = int(hoogte * mm / 4.0)
                if k["mm"] > 0 and hh < 4:
                    hh = 4
                x = r.x + 16 + i * bw
                if hh:
                    pygame.draw.rect(v, BLAUW, (x + 4, onder - hh, bw - 8, hh), border_radius=4)
                if i % 2 == 0:
                    self.tekst(k["tijd"], self.f_mini, GRIJS, x + bw / 2, onder + 6, midden=True)
        return r.bottom

    def scherm_uren(self):
        v, W, H = self.venster, self.W, self.H
        self.bovenbalk()
        uren = (self.weer or {}).get("uur") or []
        y0 = 100 - self.scroll
        oud = v.get_clip()
        v.set_clip(pygame.Rect(0, 92, W, H - 92 - 112))
        for i, u in enumerate(uren):
            y = y0 + i * 92
            if y > H or y < 0:
                continue
            pygame.draw.rect(v, PANEEL, (14, y, W - 28, 82), border_radius=12)
            self.tekst(u["tijd"], self.f, ZILVER, 30, y + 22)
            teken_icoon(v, u["icoon"], pygame.Rect(130, y + 4, 74, 74))
            self.tekst(self.graden(u["temp"]), self.f_groot, WIT, 330, y + 16, rechts=True)
            if u.get("regen") is not None:
                self.tekst("%d%%" % u["regen"], self.f, BLAUW if u["regen"] >= 40 else GRIJS, W - 30, y + 22, rechts=True)
        v.set_clip(oud)
        self.max_scroll = max(0, len(uren) * 92 - (H - 92 - 112) + 20)
        self.tekst("Regenkans", self.f_mini, GRIJS, W - 30, H - 134, rechts=True)
        self.onderbalk()

    def scherm_week(self):
        v, W, H = self.venster, self.W, self.H
        self.bovenbalk()
        dagen = (self.weer or {}).get("dagen") or []
        y = 100 - self.scroll
        oud = v.get_clip()
        v.set_clip(pygame.Rect(0, 92, W, H - 92 - 112))
        for i, d in enumerate(dagen):
            naam = "Vandaag" if i == 0 else "Morgen" if i == 1 else we.DAGNAAM.get(d["dag"], d["dag"])
            regels = self.breek(d.get("tekst", "").split(": ", 1)[-1], self.f_klein, W - 70)[:3]
            hoogte = 112 + 28 * len(regels)
            kl = ROOD if d.get("waarschuwing", 0) >= 2 else ORANJE if d.get("waarschuwing") else PAARS
            pygame.draw.rect(v, PANEEL, (14, y, W - 28, hoogte), border_radius=12)
            pygame.draw.rect(v, kl, (14, y, W - 28, hoogte), 3, border_radius=12)
            self.tekst(naam, self.f, ZILVER, 30, y + 14)
            teken_icoon(v, d["icoon"], pygame.Rect(W // 2 - 60, y + 6, 92, 92))
            self.tekst(self.graden(d.get("max")), self.f_groot, WIT, W - 110, y + 10, rechts=True)
            self.tekst(self.graden(d.get("min")), self.f, GRIJS, W - 30, y + 16, rechts=True)
            if d.get("regen") is not None:
                self.tekst("Regen %d%%" % d["regen"], self.f_klein, BLAUW, 30, y + 60)
            for j, t in enumerate(regels):
                self.tekst(t, self.f_klein, ZILVER, 30, y + 100 + j * 28)
            y += hoogte + 12
        v.set_clip(oud)
        self.max_scroll = max(0, y + self.scroll - (H - 112) + 20)
        self.onderbalk()

    def scherm_radar(self):
        v, W, H = self.venster, self.W, self.H
        gebied = pygame.Rect(0, 92, W, H - 92 - 112 - 70)
        p = self.plek() or (52.1, 5.3)
        z = self.radar_zoom
        cx, cy = geo.naar_pixel(p[0], p[1], z)
        ox, oy = gebied.centerx - cx, gebied.centery - cy
        oud = v.get_clip()
        v.set_clip(gebied)
        v.fill((200, 200, 196), gebied)
        x0, x1 = int((cx - gebied.w / 2) // 256), int((cx + gebied.w / 2) // 256)
        y0, y1 = int((cy - gebied.h / 2) // 256), int((cy + gebied.h / 2) // 256)
        rz = min(7, z)
        f = 2 ** (z - rz)
        beelden = self.radar.beelden
        frame = beelden[self.radar_i % len(beelden)] if beelden else None
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                img = self.kaart_tegel(z, tx, ty)
                if img:
                    v.blit(img, (tx * 256 + ox, ty * 256 + oy))
        if frame:
            T = 256 * f
            rx0, rx1 = int((cx - gebied.w / 2) // T), int((cx + gebied.w / 2) // T)
            ry0, ry1 = int((cy - gebied.h / 2) // T), int((cy + gebied.h / 2) // T)
            for ty in range(ry0, ry1 + 1):
                for tx in range(rx0, rx1 + 1):
                    img = self.radar_tegel(frame[1], rz, tx, ty, T)
                    if img:
                        v.blit(img, (tx * T + ox, ty * T + oy))
        pygame.draw.circle(v, ZWART, (gebied.centerx, gebied.centery), 13)
        pygame.draw.circle(v, GEEL, (gebied.centerx, gebied.centery), 9)
        img = self.f_mini.render("Radar: RainViewer   Kaart: © OpenStreetMap-bijdragers", True, (40, 40, 40))
        v.blit(img, (gebied.right - img.get_width() - 6, gebied.bottom - img.get_height() - 4))
        v.set_clip(oud)
        # bovenbalk en bediening
        pygame.draw.rect(v, ZWART, (0, 0, W, 92))
        self.bovenbalk()
        balk = pygame.Rect(0, gebied.bottom, W, 70)
        pygame.draw.rect(v, PANEEL, balk)
        if frame:
            laatste = self.radar_i % len(beelden) == len(beelden) - 1
            t = time.strftime("%H:%M", time.localtime(frame[0]))
            self.tekst(("Nu  " if laatste else "") + t, self.f_groot, GEEL if laatste else ZILVER, 20, balk.y + 14)
        else:
            self.tekst("Radar laden...", self.f, GRIJS, 20, balk.y + 20)
        self.knop((W - 300, balk.y + 8, 84, 56), "-", lambda: self.zet_radar_zoom(-1), kleur=PANEEL, font=self.f_groot)
        self.knop((W - 206, balk.y + 8, 84, 56), "+", lambda: self.zet_radar_zoom(1), kleur=PANEEL, font=self.f_groot)
        self.knop((W - 112, balk.y + 8, 96, 56), "Pauze" if self.radar_speel else "Speel",
                  lambda: setattr(self, "radar_speel", not self.radar_speel), kleur=PANEEL, font=self.f_mid)
        self.onderbalk()

    def zet_radar_zoom(self, d):
        self.radar_zoom = max(5, min(9, self.radar_zoom + d))

    def kaart_tegel(self, z, x, y):
        n = 2 ** z
        if not 0 <= y < n:
            return None
        k = ("osm", z, x % n, y)
        if k in self.plaatjes:
            return self.plaatjes[k]
        if k in self.tegels.klaar:
            data = self.tegels.klaar.pop(k)
            try:
                img = pygame.image.load(io.BytesIO(data), "t.png").convert() if data else None
            except Exception:
                img = None
            if img:
                self.plaatjes[k] = img
            return img
        self.tegels.vraag(z, x % n, y)
        return None

    def radar_tegel(self, pad, z, x, y, T):
        n = 2 ** z
        if not 0 <= y < n:
            return None
        k = ("radar", pad, z, x % n, y, T)
        if k in self.plaatjes:
            return self.plaatjes[k]
        bron = (pad, z, x % n, y)
        if bron in self.radar.klaar:
            data = self.radar.klaar[bron]
            img = None
            if data:
                try:
                    img = pygame.image.load(io.BytesIO(data), "r.png").convert_alpha()
                    if T != 256:
                        img = pygame.transform.smoothscale(img, (T, T))
                except Exception:
                    img = None
            self.plaatjes[k] = img
            if len(self.plaatjes) > 260:
                del self.plaatjes[next(iter(self.plaatjes))]
            return img
        self.radar.vraag(pad, z, x % n, y)
        return None

    def scherm_zoek(self):
        v, W, H = self.venster, self.W, self.H
        self.knop((16, 16, 140, 70), "Terug", lambda: self.naar("nu"), kleur=PANEEL)
        self.tekst("Welke plaats?", self.f, ZILVER, 172, 34)
        vak = pygame.Rect(16, 104, W - 32, 80)
        pygame.draw.rect(v, WIT, vak, border_radius=12)
        pygame.draw.rect(v, GEEL, vak, 4, border_radius=12)
        t = self.zoektekst + ("|" if int(self.tijd * 2) % 2 == 0 else " ")
        while self.f_groot.size(t)[0] > vak.w - 24 and len(t) > 1:
            t = t[1:]
        self.tekst(t, self.f_groot, ZWART, vak.x + 14, vak.y + 16)
        self.knoppen.append((vak, lambda: pygame.key.start_text_input()))
        self.knop((16, 198, W - 32, 74), "Zoeken", self.zoek, kleur=PAARS, rand=GEEL, tekstkleur=ZWART)
        self.knop((16, 286, W - 32, 74), "Mijn plek (GPS)", lambda: self.kies_plaats(None), kleur=PANEEL, rand=GEEL)
        y = 378
        lijst = self.resultaten or self.inst.get("recent", [])
        if lijst and not self.resultaten:
            self.tekst("Eerder gekozen:", self.f_klein, GRIJS, 20, y)
            y += 32
        for r in lijst[:7]:
            if y + 84 > H - 10:
                break
            onder = ", ".join(x for x in (r.get("regio"), r.get("land")) if x)
            self.knop((16, y, W - 32, 80), "", lambda r=r: self.kies_plaats(r), kleur=PANEEL)
            self.tekst(r["naam"], self.f, ZILVER, 34, y + 10, max_b=W - 70)
            if onder:
                self.tekst(onder, self.f_klein, GRIJS, 34, y + 46, max_b=W - 70)
            y += 92

    def teken(self):
        self.knoppen = []
        self.venster.fill(ZWART)
        getattr(self, "scherm_" + self.scherm)()
        tekst = None
        if self.bezig == "zoeken":
            tekst = "Zoeken..."
        elif self.melding and time.time() < self.melding[1]:
            tekst = self.melding[0]
        if tekst:
            r = pygame.Rect(30, self.H // 2 - 50, self.W - 60, 100)
            pygame.draw.rect(self.venster, PANEEL, r, border_radius=16)
            pygame.draw.rect(self.venster, GEEL, r, 4, border_radius=16)
            self.tekst(tekst, self.f, ZILVER, r.centerx, r.y + 32, midden=True, max_b=r.w - 30)
        pygame.display.flip()

    # ------------------------------------------------------------ hoofdlus
    def klik(self, pos):
        for r, actie in reversed(self.knoppen):
            if r.collidepoint(pos):
                actie()
                return

    def run(self):
        self.stem.zeg(["welkom"])
        while not self.stop:
            dt = self.klok.tick(30) / 1000.0
            self.tijd += dt
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.stop = True
                elif e.type == pygame.KEYDOWN:
                    if e.key in (pygame.K_AC_BACK, pygame.K_ESCAPE):
                        if self.scherm == "nu":
                            self.stop = True
                        else:
                            self.naar("nu")
                    elif self.scherm == "zoek" and e.key == pygame.K_BACKSPACE:
                        self.zoektekst = self.zoektekst[:-1]
                    elif self.scherm == "zoek" and e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self.zoek()
                elif e.type == pygame.TEXTINPUT and self.scherm == "zoek":
                    self.zoektekst = (self.zoektekst + e.text)[:40]
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.sleep = (e.pos, self.scroll, False)
                elif e.type == pygame.MOUSEMOTION and self.sleep and e.buttons[0]:
                    (sx, sy), s0, _ = self.sleep
                    if abs(e.pos[1] - sy) > 20 and self.scherm in ("uren", "week"):
                        self.scroll = max(0, min(getattr(self, "max_scroll", 0), s0 - (e.pos[1] - sy)))
                        self.sleep = ((sx, sy), s0, True)
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                    if self.sleep and not self.sleep[2]:
                        self.klik(e.pos)
                    self.sleep = None
            self.verwerk()
            self.haal()
            if self.scherm == "radar":
                self.radar.ververs()
                n = len(self.radar.beelden)
                if n and self.radar_speel:
                    self.radar_t += dt
                    wacht = 2.0 if self.radar_i % n == n - 1 else 0.5
                    if self.radar_t > wacht:
                        self.radar_t = 0
                        self.radar_i = (self.radar_i + 1) % n
                elif n and not self.radar_speel:
                    self.radar_i = n - 1
            self.stem.update()
            self.teken()
        pygame.quit()


def main():
    Weer().run()


if __name__ == "__main__":
    main()
