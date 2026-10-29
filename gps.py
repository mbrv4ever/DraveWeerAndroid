# -*- coding: utf-8 -*-
# DraveNavi - Copyright (C) 2026 Dravenlock (Roger & Claudio).
"""gps.py - je plek. Op de telefoon via Android (pyjnius), op de pc een vaste of nagebootste plek."""
import os
import threading
import time

ANDROID = "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ


class Gps:
    def __init__(self):
        self.plek = None          # (lat, lon)
        self.nauwkeurig = None    # meters
        self.koers = None         # graden, None als je stilstaat
        self.snelheid = 0.0       # m/s
        self.tijd = 0.0           # wanneer laatst bijgewerkt
        self.status = "uit"       # uit | wacht | aan | geen_toestemming | fout
        self.demo = None          # nagebootste rit: lijst punten
        self._lock = threading.Lock()
        self._luister = None

    # ------------------------------------------------------------ starten
    def start(self):
        if not ANDROID:
            self.status = "aan"
            if self.plek is None:
                self.zet(52.0894, 5.1101, 8)     # pc: een plek om mee te testen (Utrecht Centraal)
            return
        self.status = "wacht"
        try:
            from android.permissions import Permission, request_permissions
            request_permissions([Permission.ACCESS_FINE_LOCATION, Permission.ACCESS_COARSE_LOCATION], self._toestemming)
        except Exception:
            self._toestemming(None, [True])

    def _toestemming(self, perms, gegeven):
        if gegeven and not all(gegeven):
            self.status = "geen_toestemming"
            return
        try:
            self._android_start()
        except Exception as e:
            self.status = "fout"
            self.foutmelding = str(e)

    def _android_start(self):
        from jnius import PythonJavaClass, autoclass, java_method
        Context = autoclass("android.content.Context")
        Looper = autoclass("android.os.Looper")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        gps = self

        class Luisteraar(PythonJavaClass):
            __javainterfaces__ = ["android/location/LocationListener"]
            __javacontext__ = "app"

            @java_method("(Landroid/location/Location;)V")
            def onLocationChanged(self, loc):
                gps.zet(loc.getLatitude(), loc.getLongitude(), loc.getAccuracy(),
                        loc.getBearing() if loc.hasBearing() else None, loc.getSpeed() if loc.hasSpeed() else 0.0)

            @java_method("(Ljava/lang/String;)V")
            def onProviderEnabled(self, p):
                pass

            @java_method("(Ljava/lang/String;)V")
            def onProviderDisabled(self, p):
                pass

            @java_method("(Ljava/lang/String;ILandroid/os/Bundle;)V")
            def onStatusChanged(self, p, s, extra):
                pass

        lm = act.getSystemService(Context.LOCATION_SERVICE)
        self._luister = Luisteraar()
        for bron in ("gps", "network"):
            try:
                if lm.isProviderEnabled(bron):
                    lm.requestLocationUpdates(bron, 1000, 0.0, self._luister, Looper.getMainLooper())
                    laatste = lm.getLastKnownLocation(bron)
                    if laatste is not None and self.plek is None:
                        self.zet(laatste.getLatitude(), laatste.getLongitude(), laatste.getAccuracy())
            except Exception:
                pass
        self.status = "aan"

    # ------------------------------------------------------------ bijwerken
    def zet(self, lat, lon, nauwkeurig=10, koers=None, snelheid=0.0):
        with self._lock:
            self.plek = (lat, lon)
            self.nauwkeurig = nauwkeurig
            if koers is not None and snelheid > 0.7:
                self.koers = koers
            self.snelheid = snelheid
            self.tijd = time.time()

    def oud(self):
        """Seconden sinds de laatste plek (groot = geen signaal)."""
        return time.time() - self.tijd if self.tijd else 1e9

    # ------------------------------------------------------------ demo: rij de route na (om te testen)
    def start_demo(self, punten, snelheid_ms):
        self.demo = dict(punten=punten, i=0, f=0.0, v=snelheid_ms, t=time.time())

    def stop_demo(self):
        self.demo = None

    def update(self):
        d = self.demo
        if not d:
            return
        import geo
        nu = time.time()
        stap = (nu - d["t"]) * d["v"]
        d["t"] = nu
        p = d["punten"]
        while stap > 0 and d["i"] < len(p) - 1:
            a, b = p[d["i"]], p[d["i"] + 1]
            lang = max(0.01, geo.afstand(a, b))
            over = lang * (1 - d["f"])
            if stap < over:
                d["f"] += stap / lang
                stap = 0
            else:
                stap -= over
                d["i"] += 1
                d["f"] = 0.0
        i = min(d["i"], len(p) - 2)
        a, b = p[i], p[i + 1]
        lat = a[0] + (b[0] - a[0]) * d["f"]
        lon = a[1] + (b[1] - a[1]) * d["f"]
        self.zet(lat, lon, 5, geo.koers(a, b), d["v"])
        if d["i"] >= len(p) - 1:
            self.demo = None
