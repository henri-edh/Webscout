# 🕵️ Scout: Advanced Web Parsing Library

## 🌟 Overview

Scout is a powerful web parsing library designed to provide flexible and intelligent HTML and XML parsing. With advanced features like web crawling and Markdown conversion, Scout goes beyond traditional parsing libraries.

## ✨ New Features

### 🌐 Web Crawling

Easily crawl websites:

```python
from webscout.scout import ScoutCrawler

# Crawl a website
crawler = ScoutCrawler('https://example.com')
crawled_pages = crawler.crawl()

for page in crawled_pages:
    print(f"URL: {page['url']}")
    print(f"Title: {page['title']}")

```

## 🚀 Core Features

- **Multiple Parser Support**
  - Built-in parsers: `html.parser`, `lxml`, `html5lib`
  - Easily switch between parsing strategies
  - Custom parser registration

- **Advanced Parsing Capabilities**
  - Robust element traversal
  - CSS selector support
  - Text extraction
  - Tag manipulation
  - Web crawling
  - Markdown conversion

- **Intelligent Parsing**
  - Concurrent web crawling
  - Domain-based link extraction
  - Semantic information extraction

## 📦 Installation

```bash
pip install webscout
```

## 💡 Quick Start

### Basic Parsing

```python
from webscout.scout import Scout

# Parse HTML
html_content = """
<html>
    <body>
        <h1>Hello, Scout!</h1>
        <div class="content">
            <p>Web parsing made easy.</p>
            <a href="https://example.com">Link</a>
        </div>
    </body>
</html>
"""

scout = Scout(html_content)

# Find elements
title = scout.find('h1')
links = scout.find_all('a')

# Extract text
print(title.texts()[0])  # Output: Hello Scout!

```

## 🔧 Dependencies

- requests
- lxml
- markdownify
- concurrent.futures

## 🌈 Supported Python Versions

- Python 3.8+

## 🤝 Contributing

Contributions are welcome! Please check our GitHub repository for guidelines.
