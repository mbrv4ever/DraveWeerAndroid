# -*- coding: utf-8 -*-
# Dravenlock (Roger & Claudio) - vraagt de eerste keer of het icoon op het startscherm moet.
"""Android zet bij zelf geïnstalleerde apps geen icoon op het startscherm. Deze vraagt het één keer netjes."""
import os


def vraag(naam):
    prive = os.environ.get("ANDROID_PRIVATE")
    if not prive:
        return                                        # niet op Android
    vlag = os.path.join(prive, ".startscherm_gevraagd")
    if os.path.exists(vlag):
        return
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass, cast

        @run_on_ui_thread
        def doe():
            try:
                act = autoclass("org.kivy.android.PythonActivity").mActivity
                ctx = cast("android.content.Context", act)
                if autoclass("android.os.Build$VERSION").SDK_INT < 26:
                    return
                sm = cast("android.content.pm.ShortcutManager", act.getSystemService("shortcut"))
                if not sm.isRequestPinShortcutSupported():
                    return
                intent = act.getPackageManager().getLaunchIntentForPackage(act.getPackageName())
                icoon = autoclass("android.graphics.drawable.Icon").createWithResource(ctx, act.getApplicationInfo().icon)
                info = autoclass("android.content.pm.ShortcutInfo$Builder")(ctx, "drave_start") \
                    .setShortLabel(naam).setLongLabel(naam).setIcon(icoon).setIntent(intent).build()
                sm.requestPinShortcut(info, None)
                open(vlag, "w").write("ja")              # pas onthouden als het gelukt is
            except Exception as e:
                try:
                    open(os.path.join(prive, "startscherm_fout.txt"), "w").write(repr(e))
                except Exception:
                    pass
        import threading
        threading.Timer(5.0, doe).start()          # pas als de app helemaal open is, anders drukt die het venster weg
    except Exception:
        pass
