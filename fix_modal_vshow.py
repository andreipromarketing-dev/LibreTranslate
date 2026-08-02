with open('libretranslate/templates/index.html', 'r') as f:
    content = f.read()

# Change v-if to v-show for modal overlays
content = content.replace('v-if="glossaryModalOpen"', 'v-show="glossaryModalOpen"')
content = content.replace('v-if="abbrModalOpen"', 'v-show="abbrModalOpen"')
content = content.replace('v-if="filePreview !== false"', 'v-show="filePreview !== false"')

with open('libretranslate/templates/index.html', 'w') as f:
    f.write(content)

print('Changed v-if to v-show for modals')