with open('libretranslate/templates/index.html', 'r') as f:
    content = f.read()
    idx = content.find('id="app"')
    if idx >= 0:
        print('app root at:', idx)
        idx2 = content.find('glossaryModalOpen')
        print('modal at:', idx2)
        if idx2 > idx:
            print('Modal is INSIDE app root')
        else:
            print('Modal is OUTSIDE app root!')