# -*- coding: utf-8 -*-
# DraveWeer - opstarter. Elke fout (ook bij het laden) komt op het scherm in plaats van stil te sluiten.
import os
import sys
import traceback


def fout_scherm(tekst):
    try:
        map_ = os.path.join(os.environ.get("ANDROID_PRIVATE") or os.path.dirname(os.path.abspath(__file__)), "DraveWeer-data")
        os.makedirs(map_, exist_ok=True)
        open(os.path.join(map_, "fout.txt"), "w", encoding="utf-8").write(tekst)
    except Exception:
        pass
    try:
        import pygame
        pygame.init()
        scherm = pygame.display.get_surface() or pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        w, h = scherm.get_size()
        ttf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "DejaVuSans.ttf")
        f = pygame.font.Font(ttf if os.path.exists(ttf) else None, max(22, h // 26))
        regels = ["Oeps, er ging iets mis. Maak een screenshot en meld het via dravenlock.nl:", ""]
        for r in tekst.strip().splitlines()[-14:]:
            while len(r) > 90:
                regels.append(r[:90]); r = "   " + r[90:]
            regels.append(r)
        regels += ["", "Tik op het scherm om te sluiten."]
        while True:
            for e in pygame.event.get():
                if e.type in (pygame.QUIT, pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN, pygame.KEYDOWN):
                    return
            scherm.fill((20, 6, 10))
            for i, r in enumerate(regels):
                scherm.blit(f.render(r, True, (255, 230, 200)), (20, 20 + i * int(f.get_height() * 1.15)))
            pygame.display.flip()
            pygame.time.wait(50)
    except Exception:
        pass


try:
    import startscherm
    startscherm.vraag('DraveWeer')
except Exception:
    pass

try:
    import weer
    weer.main()
except SystemExit:
    pass
except Exception:
    fout_scherm(traceback.format_exc())
