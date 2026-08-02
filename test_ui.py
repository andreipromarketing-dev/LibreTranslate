import sys
sys.path.insert(0, '.')
from libretranslate.app import create_app

class Args:
    host = '0.0.0.0'
    port = 5000
    load_only = 'en,ru'
    disable_files_translation = False
    char_limit = 5000
    req_limit = 60
    req_limit_storage = 'memory://'
    hourly_req_limit = 0
    hourly_req_limit_decay = 0.5
    daily_req_limit = 0
    req_flood_threshold = 10
    req_time_cost = 0
    batch_limit = 0
    debug = False
    ssl = False
    frontend_language_source = 'auto'
    frontend_language_target = 'locale'
    frontend_language = 'en'
    frontend_title = ''
    frontend_timeout = 500
    api_keys = False
    api_keys_db_path = 'data/api_keys.db'
    api_keys_remote = ''
    get_api_key_link = ''
    require_api_key_origin = ''
    require_api_key_secret = False
    require_api_key_fingerprint = False
    hide_api = False
    under_attack = False
    shared_storage = 'memory://'
    secondary = False
    url_prefix = ''
    req_time_cost = 0
    trust_forwarded_for = False
    update_models = False
    force_update_models = False
    metrics = False
    metrics_auth_token = ''
    translation_cache = ''
    suggestions = False
    disable_web_ui = False
    pdf_backend = 'pymupdf'

app = create_app(Args())
print('App created successfully')

with app.test_client() as client:
    r = client.get('/')
    html = r.get_data(as_text=True)
    if '[[ glossaryModalTitle ]]' in html:
        print('FAIL: Raw template syntax found')
    else:
        print('OK: No raw template syntax')
    if 'v-if="glossaryModalOpen"' in html:
        print('OK: v-if present')
    else:
        print('FAIL: v-if missing')
    if 'v-cloak' in html:
        print('OK: v-cloak present')
    else:
        print('FAIL: v-cloak missing')