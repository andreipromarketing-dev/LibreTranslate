import fitz
import os

doc = fitz.open()
page = doc.new_page()
text = 'Hello world! This is a test document with sufficient text content. ' * 10
text += 'Machine learning is a subset of artificial intelligence. ' * 10
text += 'Neural networks are a key component of modern machine learning systems. ' * 10
text += 'Deep learning uses neural networks with multiple layers. ' * 10
text += 'Supervised learning learns from labeled data. ' * 10
text += 'Unsupervised learning finds patterns without labels. ' * 10
text += 'Reinforcement learning maximizes cumulative reward. ' * 10
text += 'Natural language processing deals with human language. ' * 10
text += 'Computer vision interprets visual world. ' * 10
text += 'Robotics integrates computer science and engineering. ' * 10
page = doc.new_page()
page.insert_text((50, 50), text)
doc.save(os.path.join(os.environ['TEMP'], 'test_cli_long.pdf'))
print('Long test PDF created')