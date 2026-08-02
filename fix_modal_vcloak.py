with open('libretranslate/templates/index.html', 'r') as f:
    content = f.read()

# Revert v-show back to v-if with v-cloak
content = content.replace('v-show="glossaryModalOpen"', 'v-if="glossaryModalOpen" v-cloak')
content = content.replace('v-show="abbrModalOpen"', 'v-if="abbrModalOpen" v-cloak')
content = content.replace('v-show="filePreview !== false"', 'v-if="filePreview !== false" v-cloak')

with open('libretranslate/templates/index.html', 'w') as f:
    f.write(content)

print('Changed v-show back to v-if with v-cloak')