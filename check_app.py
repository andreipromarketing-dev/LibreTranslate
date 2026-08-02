with open('libretranslate/templates/index.html', 'r') as f:
    content = f.read()
    idx = content.find('id="app"')
    if idx >= 0:
        print(content[idx:idx+200])