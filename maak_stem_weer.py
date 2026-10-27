# -*- coding: utf-8 -*-
# DraveWeer Android - Copyright (C) 2026 Dravenlock (Roger & Claudio).
"""maak_stem_weer.py - Leon (neuvoice) spreekt alle weerzinnetjes in. Draai: py -3.10 maak_stem_weer.py -> map stem_weer"""
import os
import wave

import numpy as np

GETAL = ["nul", "een", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien", "elf", "twaalf", "dertien",
         "veertien", "vijftien", "zestien", "zeventien", "achttien", "negentien", "twintig", "eenentwintig", "tweeëntwintig",
         "drieëntwintig", "vierentwintig", "vijfentwintig", "zesentwintig", "zevenentwintig", "achtentwintig", "negenentwintig",
         "dertig", "eenendertig", "tweeëndertig", "drieëndertig", "vierendertig", "vijfendertig", "zesendertig",
         "zevenendertig", "achtendertig", "negenendertig", "veertig"]
ZINNEN = {"n%d" % i: w for i, w in enumerate(GETAL)}
ZINNEN.update({
    "min": "min",
    "graden": "graden.",
    "graden_en": "graden, en",
    "het_is_nu": "Het is nu",
    "vandaag_max": "Vandaag wordt het maximaal",
    "morgen": "Morgen:",
    "max": "maximaal",
    "c_zon": "zonnig.", "c_halfbewolkt": "half bewolkt.", "c_bewolkt": "bewolkt.", "c_mist": "mistig.",
    "c_motregen": "motregen.", "c_regen": "regen.", "c_sneeuw": "sneeuw.", "c_buien": "buien.", "c_onweer": "onweer.",
    "droog_2u": "Het blijft de komende twee uur droog.",
    "regent_nu": "Het regent nu.",
    "regen_over": "Over",
    "m15": "een kwartier", "m30": "een half uur", "m45": "drie kwartier", "m60": "een uur", "m90": "anderhalf uur",
    "m120": "twee uur",
    "gaat_regenen": "gaat het regenen.",
    "stopt_over": "Het wordt droog over",
    "w_vrij_krachtige_wind": "Er staat een vrij krachtige wind.", "w_harde_wind": "Er staat een harde wind.",
    "w_stormachtige_wind": "Er staat een stormachtige wind.", "w_storm": "Let op: het stormt.",
    "w_zware_storm": "Let op: zware storm.", "w_zeer_zware_storm": "Let op: zeer zware storm.",
    "let_stoten": "Let op: zware windstoten.",
    "let_onweer": "Let op: kans op onweer.",
    "let_vorst": "Let op: kans op vorst en gladheid.",
    "let_tropisch": "Het wordt tropisch warm. Drink genoeg water.",
    "welkom": "Welkom bij Dreev Weer.",
    "geen_internet": "Er is geen internet. Ik probeer het zo opnieuw.",
})


def main():
    from neuvoice import TTS
    uit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stem_weer")
    os.makedirs(uit, exist_ok=True)
    tts = TTS(auto_download=True)
    namen = list(getattr(tts, "voice_style_names", []) or [])
    stijl = tts.get_voice_style("Leon" if "Leon" in namen else namen[0])
    sr = int(getattr(tts, "sample_rate", 44100) or 44100)
    for sleutel, tekst in ZINNEN.items():
        wav, _ = tts.synthesize(tekst, voice_style=stijl, total_steps=10, speed=0.9, lang="nl")
        x = np.asarray(wav, dtype=np.float32).flatten()
        drempel = 0.01 * (np.max(np.abs(x)) or 1)
        waar = np.where(np.abs(x) > drempel)[0]
        if len(waar):
            x = x[max(0, waar[0] - int(sr * 0.02)): waar[-1] + int(sr * 0.06)]
        x = np.concatenate([np.zeros(int(sr * 0.06), np.float32), x, np.zeros(int(sr * 0.06), np.float32)])
        n = int(len(x) * 22050 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
        x = x / (np.max(np.abs(x)) or 1) * 0.9
        with wave.open(os.path.join(uit, sleutel + ".wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes((x * 32767).astype("<i2").tobytes())
    print("KLAAR", len(ZINNEN))


if __name__ == "__main__":
    main()
