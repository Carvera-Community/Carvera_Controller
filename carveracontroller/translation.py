# This module provides translation functionality for the Carvera Controller
# application that can be shared across all modules in the application.

from __future__ import annotations

import gettext
import locale
import os

from kivy.lang import Observable

LANGS = {
    "en": "English",
    "pt-BR": "Português (Brasil)",
    "zh-CN": "中文简体(Simplified Chinese)",
}


class Lang(Observable):
    observers = []
    lang = None

    def __init__(self, defaultlang):
        super().__init__()
        self.ugettext = None
        self.lang = defaultlang
        self.switch_lang(self.lang)

    def _(self, text):
        return self.ugettext(text)

    def fbind(self, name, func, args, **kwargs):
        if name == "_":
            self.observers.append((func, args, kwargs))
        else:
            return super().fbind(name, func, *args, **kwargs)

    def funbind(self, name, func, args, **kwargs):
        if name == "_":
            key = (func, args, kwargs)
            if key in self.observers:
                self.observers.remove(key)
        else:
            return super().funbind(name, func, *args, **kwargs)

    def switch_lang(self, lang):
        # get the right locales directory, and instanciate a gettext
        locale_dir = os.path.join(os.path.dirname(__file__), "locales")
        locales = None
        try:
            locales = gettext.translation(lang, locale_dir, languages=[lang])
        except:
            pass
        if locales == None:
            locales = gettext.NullTranslations()
        self.ugettext = locales.gettext
        self.lang = lang

        # update all the kv rules attached to this text
        for func, largs, kwargs in self.observers:
            func(largs, None, None)


# Proxy class is needed to allow for from carveracontroller.translation import tr.
# Without proxy, the initialization of the translation module would fail
# because the tr object is copied from the module to the caller's namespace
# before the translation is initialized.
class TrProxy:
    def __getattr__(self, name):
        if _translator is None:
            raise RuntimeError("Translation not initialized")
        return getattr(_translator, name)


_translator: Lang | None = Lang("en")
tr = TrProxy()


def init(langname: str | None = None):
    if langname is None or langname not in LANGS:
        try:
            default_locale = locale.getdefaultlocale()
            if default_locale is not None and default_locale[0] is not None:
                for lang_key in LANGS:
                    if default_locale[0][0:2] in lang_key:
                        langname = lang_key
                        break
        except:
            pass
    if langname is None:
        langname = "en"

    global _translator
    _translator = Lang(langname)
