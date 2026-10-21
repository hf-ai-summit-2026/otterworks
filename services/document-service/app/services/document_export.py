"""Render a document as HTML, Markdown or plain text for download."""

import html as html_mod

from app.models.document import Document


class DocumentExporter:
    def export_document(self, document: Document, fmt: str) -> tuple[str, str]:
        if fmt == "html":
            safe_title = html_mod.escape(document.title)
            safe_content = html_mod.escape(document.content)
            markup = (
                f"<html><head><title>{safe_title}</title></head>"
                f"<body><h1>{safe_title}</h1>"
                f"<div>{safe_content}</div></body></html>"
            )
            return markup, "text/html"
        if fmt == "markdown":
            md = f"# {document.title}\n\n{document.content}"
            return md, "text/markdown"
        # pdf → return simple text representation
        text = f"TITLE: {document.title}\n\n{document.content}"
        return text, "application/pdf"
