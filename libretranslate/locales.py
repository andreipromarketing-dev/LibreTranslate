import json
import os
from functools import lru_cache

from flask_babel import gettext as _
from flask_babel import lazy_gettext as _lazy
from markupsafe import Markup, escape


@lru_cache(maxsize=None)
def get_available_locales(only_reviewed=True, sort_by_name=False):
    locales_dir = os.path.join(os.path.dirname(__file__), 'locales')
    dirs = [os.path.join(locales_dir, d) for d in os.listdir(locales_dir)]

    res = [{'code': 'en', 'name': 'English', 'reviewed': True}]

    for d in dirs:
        if d == 'en':
            continue

        meta_file = os.path.join(d, 'meta.json')
        if os.path.isdir(os.path.join(d, 'LC_MESSAGES')) and os.path.isfile(meta_file):
            try:
                with open(meta_file) as f:
                    j = json.loads(f.read())
            except Exception as e:
                print(e)
                continue

            if j.get('reviewed') or not only_reviewed:
                res.append({'code': os.path.basename(d), 'name': j.get('name', ''), 'reviewed': j.get('reviewed', False)})

    if sort_by_name:
        res.sort(key=lambda s: s['name'])

    return res

@lru_cache(maxsize=None)
def get_available_locale_codes(only_reviewed=True):
    return [l['code'] for l in get_available_locales(only_reviewed=only_reviewed)]

@lru_cache(maxsize=None)
def get_alternate_locale_links():
    tmpl = os.environ.get("LT_LOCALE_LINK_TEMPLATE")
    if tmpl is None:
        return []

    locales = get_available_locale_codes()
    result = []
    for l in locales:
        link = tmpl.replace("{LANG}", l)
        if l == 'en':
            link = link.replace("en.", "")
        result.append({ 'link': link,'lang': l })
    return result

# Javascript code should use _e instead of _
def gettext_escaped(text, **variables):
    return json.dumps(_(text, **variables))

# HTML should be escaped using _h instead of _
def gettext_html(text, **variables):
    # Translate text without args
    s = str(escape(_(text)))

    v = {}
    if variables:
        for k in variables:
            if hasattr(variables[k], 'unescape'):
                v[k] = variables[k].unescape()
            else:
                v[k] = Markup(variables[k])

    # Variables are assumed to be already escaped and thus safe
    return Markup(s if not v else s % v)

def swag_eval(swag, func):
    # Traverse the swag spec structure
    # and call func on summary and description keys
    for k in swag:
        if k in ['summary', 'description'] and isinstance(swag[k], str) and swag[k] != "":
            swag[k] = func(swag[k])
        elif k == 'tags' and isinstance(swag[k], list):
            swag[k] = [func(v) for v in swag[k]]
        elif isinstance(swag[k], dict):
            swag_eval(swag[k], func)
        elif isinstance(swag[k], list) and k != 'consumes':
            for i in swag[k]:
                if isinstance(i, str):
                    func(i)
                elif isinstance(i, dict):
                    swag_eval(i, func)

    return swag

def lazy_swag(swag):
    return swag_eval(swag, _lazy)


@lru_cache(maxsize=None)
def get_translations_for_locale(locale: str) -> dict:
    """Load all translation strings for a given locale."""
    import json
    import os
    
    # Get the path to the locale's .po file
    locales_dir = os.path.join(os.path.dirname(__file__), 'locales')
    po_file = os.path.join(locales_dir, locale, 'LC_MESSAGES', 'messages.po')
    
    if not os.path.exists(po_file):
        return {}
    
    translations = {}
    
    try:
        with open(po_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse .po file
        entries = content.split('\n\n')
        current_msgid = None
        current_msgstr = None
        
        for entry in entries:
            lines = entry.strip().split('\n')
            msgid = None
            msgstr = None
            for line in lines:
                line = line.strip()
                if line.startswith('msgid '):
                    msgid = line[6:-1]  # Remove 'msgid "' and trailing '"'
                elif line.startswith('msgstr '):
                    msgstr = line[7:-1]  # Remove 'msgstr "' and trailing '"'
            
            if msgid and msgstr and msgid != msgstr:
                # Unescape
                import codecs
                try:
                    msgid = codecs.decode(msgid, 'unicode_escape')
                    msgstr = codecs.decode(msgstr, 'unicode_escape')
                except:
                    pass
                if msgid and msgstr:
                    translations[msgid] = msgstr
    except Exception as e:
        print(f"Error loading translations for {locale}: {e}")
    
    return translations