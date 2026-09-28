# Copyright © 2026 Alen Pepa.
"""Catch accidental removal of the footer attribution during packaging."""
from html.parser import HTMLParser


class FooterNoticeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_footer = False
        self.in_notice = False
        self.notices = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'footer':
            self.in_footer = True
        if self.in_footer and tag == 'span' and attrs.get('id') == 'copyrightNotice':
            if 'hidden' in attrs or attrs.get('aria-hidden') == 'true':
                raise ValueError('The copyright notice must not be hidden.')
            self.in_notice = True
            self.notices.append('')

    def handle_data(self, data):
        if self.in_notice:
            self.notices[-1] += data

    def handle_endtag(self, tag):
        if tag == 'span':
            self.in_notice = False
        if tag == 'footer':
            self.in_footer = False
            self.in_notice = False


def validate_footer(html):
    parser = FooterNoticeParser()
    parser.feed(html)
    parser.close()
    if parser.notices != ['Copyright © 2026 Alen Pepa']:
        raise ValueError('Packaging stopped: restore the Alen Pepa footer copyright notice.')
