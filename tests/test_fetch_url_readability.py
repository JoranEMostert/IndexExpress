from search.searxng_client import (
    _extract_structured_article_text,
    _post_process_markdown,
    _prepare_html_for_readability,
)


def test_prepare_html_for_readability_prefers_main_content_over_nav():
    html = """
    <html>
      <body>
        <header>Open menu Sign in</header>
        <nav>Home About Login</nav>
        <main>
          <article>
            <h1>Slug Facts</h1>
            <p>Slugs are gastropods and leave mucus trails for movement.</p>
          </article>
        </main>
        <footer>Privacy policy cookies newsletter</footer>
      </body>
    </html>
    """
    prepared = _prepare_html_for_readability(html)
    lowered = prepared.lower()
    assert "gastropods" in lowered
    assert "open menu" not in lowered
    assert "privacy policy" not in lowered


def test_post_process_markdown_removes_low_signal_lines():
    text = """
    Skip to main content
    Open menu
    Slugs are mollusks in the class Gastropoda.
    https://example.com/a https://example.com/b
    They can have thousands of microscopic teeth.
    """
    cleaned = _post_process_markdown(text)
    lowered = cleaned.lower()
    assert "skip to main content" not in lowered
    assert "open menu" not in lowered
    assert "https://example.com/a https://example.com/b" not in cleaned
    assert "mollusks" in lowered
    assert "microscopic teeth" in lowered


def test_extract_structured_article_text_prefers_article_body_jsonld():
    html = """
    <html>
      <head>
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "Slug Facts",
            "articleBody": "Slugs are soft-bodied gastropods that produce mucus for locomotion and protection."
          }
        </script>
      </head>
      <body><div>menu links etc</div></body>
    </html>
    """
    text = _extract_structured_article_text(html)
    lowered = text.lower()
    assert "slug facts" in lowered
    assert "gastropods" in lowered


def test_post_process_markdown_drops_markup_garbage_lines():
    text = """
    category-link-ANIMALS selected\" href=\"/Animals-Nature\" > Animals & Nature
    Slugs can be active at night and in damp habitats.
    class=\"foo\" data-test=\"bar\"
    """
    cleaned = _post_process_markdown(text)
    lowered = cleaned.lower()
    assert "category-link-animals" not in lowered
    assert "class=\"foo\"" not in lowered
    assert "damp habitats" in lowered
