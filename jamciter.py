# type: ignore
from __future__ import print_function, absolute_import, division
import sublime
import sublime_plugin

from pathlib import Path
import sys
import os.path
import string
import re
import unicodedata
from collections import defaultdict
from imp import reload
import dateutil.parser

# ST3 loads each package as a module, so it needs an extra prefix

reloader_name = 'jamciter.reloader'
reloader_name = 'JAMCiter.' + reloader_name


# Make sure all dependencies are reloaded on upgrade
if reloader_name in sys.modules:
    reload(sys.modules[reloader_name])

if os.path.dirname(__file__) not in sys.path:
    sys.path.append(os.path.dirname(__file__))


import bibtexparser  # noqa: E402
from bibtexparser.customization import convert_to_unicode  # noqa: E402
from bibtexparser.bparser import BibTexParser  # noqa: E402
from bibtexparser.bwriter import to_bibtex  # noqa: E402

try:
    from pymed import PubMed
    from pymed.book import PubMedBookArticle
    from pymed.article import  PubMedArticle
    PUBMED_AVAILABLE = True
except Exception:
    PUBMED_AVAILABLE = False

try:
    from habanero import Crossref
    HABANERO_AVAILABLE = True
except Exception:
    HABANERO_AVAILABLE = False

try:
    import requests
    import json
    CHEMRXIV_AVAILABLE = True
except Exception:
    CHEMRXIV_AVAILABLE = False

# settings cache globals
BIBFILE_PATH = None
CITATION_FORMAT = None
QUICKVIEW_FORMAT = None
ENABLE_COMPLETIONS = None
COMPLETIONS_SCOPES = None
EXCLUDED_SCOPES = None

PANDOC_FIX = None
EXCLUDE = None

SEARCH_COMPLETIONS = None
CITATION_RE = None

CROSSREF_MAILTO = None
OUTPUT_BIBFILE_PATH = None
CROSSREF_LIMIT = None
PUBMED_LIMIT = None
CROSSREF_DATE_FIELD = None
CHEMRXIV_TOKEN = None

# Internal Cache globals
_PAPERS = {}
_YAMLBIB_PATH = None
_LST_MOD_TIME = {}
_DOCUMENTS = []
_MENU = None
_CITEKEYS = None

_CROSSREF = None
if PUBMED_AVAILABLE:
    _PUBMED = PubMed(tool='JAMCiter', email='joshuamitchell@anu.edu.au')


def plugin_loaded():
    """Called directly from sublime on plugin load
    """
    refresh_settings()
    refresh_caches()


def plugin_unloaded():
    pass

# Papers


def load_yamlbib_path(view):
    global _PAPERS
    global _YAMLBIB_PATH

    filename = view.file_name()
    if filename not in _PAPERS:
        _PAPERS[filename] = Paper(view)

    _YAMLBIB_PATH = _PAPERS[filename].bibpath()


def condense_whitespace(s):
    return ' '.join(str(s).split())

def escape_bibtex(s):
    return s.replace('&', r'\&')

def fmt_bibtex(s):
    s = escape_bibtex(s)
    s = condense_whitespace(s)
    return s

def strip_latex(s):
    if s is None:
        return None
    else:
        s = s.replace('{', '')
        s = s.replace('}', '')
        s = s.replace('``', '"')
        s = s.replace('\'\'', '"')
        return condense_whitespace(s)


STANDARD_TYPES = defaultdict(lambda: 'article', {
        'journal-article': 'article',
        'book-chapter': 'incollection',
        'proceedings-article': 'inproceedings'
})
for s in [
    'article',
    'book',
    'booklet',
    'conference',
    'inbook',
    'incollection',
    'inproceedings',
    'manual',
    'mastersthesis',
    'misc',
    'phdthesis',
    'proceedings',
    'techreport',
    'unpublished'
]:
    STANDARD_TYPES[s] = s


class Paper:

    _filepath = None
    _bibpath = None
    _modified = None

    def __init__(self, view):
        self.view = view
        self._filepath = view.file_name()

    def bibpath(self):

        modified = os.path.getmtime(self._filepath)
        if self._modified != modified:
            self._modified = modified
            self._bibpath = None

            text = self.view.substr(sublime.Region(0, self.view.size()))
            yamlP = re.compile(
                r'^---$.*?((^---$)|(^\.\.\.$))',
                re.MULTILINE | re.DOTALL
            )
            yamlMatch = yamlP.search(text)

            if yamlMatch:

                bibP = re.compile(r'^bibliography:', re.MULTILINE)
                bibMatch = bibP.search(yamlMatch.group())

                if bibMatch:

                    text = yamlMatch.group()[bibMatch.end():]
                    pathP = re.compile(r'\S+')
                    pathMatch = pathP.search(text)

                    if pathMatch:

                        folder = os.path.dirname(
                            os.path.realpath(self._filepath)
                        )
                        self._bibpath = os.path.join(
                            folder,
                            pathMatch.group()
                        )

        return self._bibpath

# Bibfiles


def append_bibfile(bib_path, entry):
    bibtex_db = BibTexParser('')
    print(entry)
    bibtex_db.records.append({
        k: fmt_bibtex(v)
        for k, v in entry.items()
        if v
    })
    bibtex_str = to_bibtex(bibtex_db)

    # append to the output file
    with open(bib_path, 'a') as bibtex_file:
        bibtex_file.write(bibtex_str)

    refresh_caches()


def bibfile_modifed(bib_path):
    global _LST_MOD_TIME
    bib_path = bib_path.strip()

    if not Path(bib_path).exists():
        sublime.status_message(
            "WARNING: BibTex file "
            + str(bib_path)
            + " not found"
        )
        return False

    last_modified_time = os.path.getmtime(bib_path)
    cached_modified_time = _LST_MOD_TIME.get(bib_path)
    if (
        cached_modified_time is None
        or last_modified_time != cached_modified_time
    ):
        _LST_MOD_TIME[bib_path] = last_modified_time
        return True
    else:
        return False


def load_bibfile(bib_path):
    if bib_path is None:
        sublime.status_message("WARNING: No BibTex file configured for Citer")
        return {}

    bib_path = Path(bib_path.strip())
    if not bib_path.exists():
        sublime.status_message(
            "WARNING: BibTex file "
            + str(bib_path)
            + " not found"
        )
        return {}

    with open(str(bib_path), 'r', encoding="utf-8") as bibfile:
        bp = BibTexParser(
            bibfile.read(),
            customization=convert_to_unicode,
            ignore_nonstandard_types=False
        )
        return list(bp.get_entry_list())


def refresh_settings():
    global BIBFILE_PATH
    global CITATION_FORMAT
    global COMPLETIONS_SCOPES
    global EXCLUDED_SCOPES

    global ENABLE_COMPLETIONS
    global EXCLUDE
    global PANDOC_FIX
    global QUICKVIEW_FORMAT

    global CITATION_RE
    global SEARCH_COMPLETIONS

    global CROSSREF_MAILTO
    global OUTPUT_BIBFILE_PATH
    global CROSSREF_LIMIT
    global PUBMED_LIMIT
    global CROSSREF_DATE_FIELD
    global _CROSSREF

    def get_settings(setting, default, is_path=False):
        project_data = sublime.active_window().project_data()
        project_citer_settings = project_data['settings'].get('citer', {})
        project_file = Path(sublime.active_window().project_file_name())
        project_folder = project_file.parent
        if project_data and setting in project_citer_settings:
            if is_path:
                set_paths = project_citer_settings[setting]
                if not isinstance(set_paths, list):
                    set_paths = [set_paths]

                out = [str(project_folder / path) for path in set_paths]
                return out
            else:
                return project_citer_settings[setting]
        else:
            return settings.get(setting, default)

    settings = sublime.load_settings('JAMCiter.sublime-settings')
    BIBFILE_PATH = get_settings('bibtex_file_path', None, is_path=True)
    CITATION_FORMAT = get_settings('citation_format', "@%s")
    COMPLETIONS_SCOPES = get_settings('completions_scopes', ['text.html.markdown'])  # noqa: E501
    EXCLUDED_SCOPES = get_settings('excluded_scopes', [])

    ENABLE_COMPLETIONS = get_settings('enable_completions', True)
    QUICKVIEW_FORMAT = get_settings('quickview_format', '{citekey} - {title}')
    PANDOC_FIX = get_settings('auto_merge_citations', False)
    EXCLUDE = get_settings('hide_other_completions', True)

    SEARCH_COMPLETIONS = get_settings('use_search_for_completions', False)
    CITATION_RE = get_settings('citation_regex', r'.*\[(@[a-zA-Z0-9_-]*;\s*)*?@$')  # noqa: E501

    CROSSREF_MAILTO = get_settings('crossref_mailto', None)
    OUTPUT_BIBFILE_PATH = get_settings('output_bib_file_path', None, is_path=True)  # noqa: E501
    CROSSREF_LIMIT = get_settings('crossref_limit', 20)
    PUBMED_LIMIT = get_settings('pubmed_limit', 20)
    CROSSREF_DATE_FIELD = get_settings('crossref_date_field', 'issued')
    CHEMRXIV_TOKEN = get_settings('chemrxiv_token', None)

    if OUTPUT_BIBFILE_PATH:
        if len(OUTPUT_BIBFILE_PATH) > 1:
            raise ValueError("Configure only one output_bib_file_path")
        OUTPUT_BIBFILE_PATH = OUTPUT_BIBFILE_PATH[0]

        if BIBFILE_PATH and OUTPUT_BIBFILE_PATH not in BIBFILE_PATH:
            raise ValueError(
                "output_bib_file_path should be one of the input files"
            )

    if HABANERO_AVAILABLE:
        _CROSSREF = Crossref(mailto=CROSSREF_MAILTO)

    if CHEMRXIV_TOKEN is None:
        CHEMRXIV_AVAILABLE = False


def refresh_caches():
    global _DOCUMENTS
    global _MENU
    global _CITEKEYS
    paths = []
    if BIBFILE_PATH is not None:
        if isinstance(BIBFILE_PATH, list):
            paths += [os.path.expandvars(path) for path in BIBFILE_PATH]
        else:
            paths.append(os.path.expandvars(BIBFILE_PATH))
    if _YAMLBIB_PATH is not None:
        paths.append(_YAMLBIB_PATH)

    if len(paths) == 0:
        sublime.status_message("WARNING: No BibTex file configured for Citer")
    else:
        # To avoid duplicate entries, reload all bibfiles if any were modified
        modified = False
        for single_path in paths:
            modified = modified or bibfile_modifed(single_path)
        if modified:
            _DOCUMENTS = []
            for single_path in paths:
                _DOCUMENTS += load_bibfile(single_path)

    _CITEKEYS = [doc.get('id') for doc in _DOCUMENTS]
    _MENU = _make_citekey_menu_list(_DOCUMENTS)


# Do some fancy build to get a sane list in the UI
class SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def _parse_authors(auth):
    """
    PARSE AUTHORS. Formats:
    Single Author: Lastname
    Two Authors: Lastname1 and Lastname2
    Three or More Authors: Lastname 1 et al.
    """
    try:
        authors = auth.split(' and ')
        lat = len(authors)
        if lat == 1:
            authors_abbr = authors[0]
        elif lat == 2:
            authors_abbr = authors[0] + " and " + authors[1]
        else:
            authors_abbr = authors[0] + " et. al"
    except Exception:
        authors_abbr = auth
    return authors_abbr


def _make_citekey_menu_list(bibdocs):
    citekeys = []
    for doc in bibdocs:
        menu_entry = []

        if doc.get('author') is not None:
            auths = _parse_authors(doc.get('author'))
        else:
            auths = 'Anon'
        title = string.Formatter().vformat(
            QUICKVIEW_FORMAT,
            (),
            SafeDict(
                 citekey=doc.get('id'),
                 title=doc.get('title'),
                 author=auths,
                 year=doc.get('year')
                 )
            )
        # title = QUICKVIEW_FORMAT.format(
        #     citekey=doc.get('id'), title=doc.get('title'))
        menu_entry.append(title)
        citekeys.append(menu_entry)
    citekeys = sorted(citekeys)
    return citekeys


def documents():
    refresh_caches()
    return _DOCUMENTS


def citekeys_menu():
    refresh_caches()
    return _MENU


def citekeys_list():
    refresh_caches()
    return _CITEKEYS


class CiterSearchCommand(sublime_plugin.TextCommand):

    """
    """
    def search_bibtex(self):
        selected_index = 0
        self.current_results_txt = []
        self.current_results_keys = []
        if HABANERO_AVAILABLE:
            self.current_results_txt.append([
                "Search CrossRef",
                "Insert a reference from the CrossRef database"
            ])
            self.current_results_keys.append("&crossref")
            self.habanero_index = selected_index
            selected_index += 1
        if PUBMED_AVAILABLE:
            self.current_results_txt.append([
                "Search PubMed",
                "Insert a reference from the PubMed database"
            ])
            self.current_results_keys.append("&PubMed")
            self.pubmed_index = selected_index
            selected_index += 1
        if CHEMRXIV_AVAILABLE:
            self.current_results_txt.append([
                "Search ChemRxiv",
                "Insert a reference from the ChemRxiv database"
            ])
            self.current_results_keys.append("&ChemRxiv")
            self.chemrxiv_index = selected_index
            selected_index += 1

        # Generate all the results to search
        for doc in documents():
            citekey = doc.get('id')

            txt = QUICKVIEW_FORMAT.format(
                citekey=citekey,
                title=strip_latex(doc.get('title')),
                author=strip_latex(doc.get('author')),
                year=strip_latex(doc.get('year')),
                journal=strip_latex(doc.get('journal'))
            ).splitlines()

            self.current_results_keys.append(citekey)
            self.current_results_txt.append(txt)

        self.view.window().show_quick_panel(
            self.current_results_txt,
            self._paste_bibtex,
            selected_index=selected_index
        )

    def run(self, edit):
        refresh_settings()
        self.search_bibtex()

    def run_keyonly(self, edit):
        refresh_settings()
        global CITATION_FORMAT
        CITATION_FORMAT = '%s'
        self.search_bibtex()

    def is_enabled(self):
        """Determines if the command is enabled
        """
        return True

    def _proc_item(self, item):
        date = item.get(CROSSREF_DATE_FIELD, {'date-parts': [[None]]})
        year = date['date-parts'][0][0]
        if year is None and item['type'] == 'book-chapter':
            year = 'INBOOK'

        citekey = (
            ''.join(str(item.get('author', [{}])[0].get('family', '')).split())
            + str(year)
        )
        citekey = unicodedata.normalize('NFKD', citekey)
        citekey = ''.join(
            c
            for c in citekey
            if c in
                'abcdefghijklmnopqrstuvwxyz'
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                '0123456789-_'
        )
        citekey_suffix = 'a' if citekey in self.citekeys else ''
        while citekey + citekey_suffix in self.citekeys:
            citekey_suffix = chr(ord(citekey_suffix) + 1)
        citekey = citekey + citekey_suffix
        item['citekey'] = citekey

        authors = '; '.join([
            a.get('family', '') + ', ' + a.get('given', '')
            for a in item.get('author', [{}])
        ])

        txt = QUICKVIEW_FORMAT.format(
            citekey=citekey,
            title=condense_whitespace(item['title'][0]),
            author=condense_whitespace(authors),
            year=str(year),
            journal=condense_whitespace(item['container-title'][0])
        )
        txt = txt.splitlines()
        return (citekey, txt, item)

    def _query_crossref(self, query):
        x = _CROSSREF.works(
            query=query,
            limit=CROSSREF_LIMIT,
            filter={'type': ['journal-article', 'book-chapter']},
            select=[
                'title', 'author', CROSSREF_DATE_FIELD, 'type', 'volume', 'page',
                'issue', 'DOI', 'container-title', 'editor', 'publisher'
            ]
        )
        self.current_results_items = x['message']['items']

        docs = documents()

        self.citekeys = set([doc.get('id') for doc in docs])

        if not self.current_results_items:
            sublime.status_message("CrossRef query gave no results")
            return

        self.current_results_keys, self.current_results_txt, items = zip(*[
            self._proc_item(item)
            for item in self.current_results_items
            # Skip entries without authors, and date for journal articles
            if 'author' in item and (item['type'] == 'book-chapter' or (
                CROSSREF_DATE_FIELD in item
                and item[CROSSREF_DATE_FIELD] != {'date-parts': [[None]]}
            ))
        ])
        self.current_results_items = items

        self.view.window().show_quick_panel(
            self.current_results_txt,
            self._paste_crossref
        )

        self.citekeys = None

    def _proc_pmart(self, pubmedarticle):
        pubdate = pubmedarticle.publication_date
        if isinstance(pubdate, str):
            pubdate = dateutil.parser.parse(pubdate)
        year = pubdate.year

        citekey = (
            ''.join(str(pubmedarticle.authors[0].get('lastname', '')).split())
            + str(year)
        )
        citekey = unicodedata.normalize('NFKD', citekey)
        citekey = ''.join(
            c
            for c in citekey
            if c in
                'abcdefghijklmnopqrstuvwxyz'
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                '0123456789-_'
        )
        citekey_suffix = 'a' if citekey in self.citekeys else ''
        while citekey + citekey_suffix in self.citekeys:
            citekey_suffix = chr(ord(citekey_suffix) + 1)
        citekey = citekey + citekey_suffix

        authors = '; '.join([
            (a.get('lastname') or '')
            + ', '
            + (a.get('initials') or '')
            + ' '
            + (a.get('firstname') or '')
            for a in pubmedarticle.authors
        ])

        try:
            journal = pubmedarticle.journal
        except AttributeError:
            journal = pubmedarticle.collection_title

        txt = QUICKVIEW_FORMAT.format(
            citekey=citekey,
            title=condense_whitespace(pubmedarticle.title),
            author=condense_whitespace(authors),
            year=str(year),
            journal=condense_whitespace(journal)
        ).splitlines()

        return (citekey, txt)

    def _proc_chemrxiv(self, article):
        pubdate = article["published_date"]
        pubdate = dateutil.parser.parse(pubdate)
        year = pubdate.year

        citekey = article["id"]

        txt = QUICKVIEW_FORMAT.format(
            citekey=citekey,
            title=condense_whitespace(article["title"]),
            author='',
            year=str(year),
            journal='ChemRxiv'
        ).splitlines()

        return (citekey, txt)

    def _query_pubmed(self, query):
        self.current_results_pmart = list(_PUBMED.query(
            query,
            max_results=PUBMED_LIMIT
        ))

        docs = documents()
        self.citekeys = set([doc.get('id') for doc in docs])

        if not self.current_results_pmart:
            sublime.status_message("PubMed query gave no results")
            return

        self.current_results_keys, self.current_results_txt = zip(
            *[self._proc_pmart(pmart) for pmart in self.current_results_pmart]
        )

        self.view.window().show_quick_panel(
            self.current_results_txt,
            self._paste_pubmed
        )

        self.citekeys = None

    def _query_chemrxiv(self, query):
        r = requests.post(
            "https://api.figshare.com/v2/articles/search",
            data=json.dumps({
                "item_type": 12, # Preprint
                "search_for": query
            })
        )

        r.raise_for_status()

        current_results_chemrxiv = r.json()

        if not current_results_chemrxiv:
            sublime.status_message("ChemRxiv query gave no results")
            return

        self.current_results_keys, self.current_results_txt = map(list, zip(
            *[self._proc_chemrxiv(a) for a in current_results_chemrxiv]
        ))

        self.view.window().show_quick_panel(
            self.current_results_txt,
            self._paste_chemrxiv
        )


    def search_external(self, dbname, queryfunc):
        self.view.window().show_input_panel(
            "Search {dbname}".format(**locals()),
            "",
            on_done=queryfunc,
            on_change=None,
            on_cancel=None
        )

    def _paste(self, index):
        """Paste index into buffer
        """
        if index == -1:
            return

        ent = self.current_results_keys[index]
        citekey = CITATION_FORMAT % ent
        if PANDOC_FIX:
            self.view.run_command('insert', {'characters': citekey})
            self.view.run_command('citer_combine_citations')
        else:
            self.view.run_command('insert', {'characters': citekey})

    def _paste_bibtex(self, index):
        if HABANERO_AVAILABLE and index == self.habanero_index:
            return self.search_external("CrossRef", self._query_crossref)
        if PUBMED_AVAILABLE and index == self.pubmed_index:
            return self.search_external("PubMed", self._query_pubmed)
        if CHEMRXIV_AVAILABLE and index == self.chemrxiv_index:
            return self.search_external("ChemRxiv", self._query_chemrxiv)

        return self._paste(index)

    def _paste_crossref(self, index):
        item = self.current_results_items[index]
        date_issued = item.get(CROSSREF_DATE_FIELD, {'date-parts': [['']]})

        bibtex_entry = {
            'id': self.current_results_keys[index],
            'type': STANDARD_TYPES[item['type']],

            'title': item.get('title', [''])[0],
            'volume': item.get('volume', ''),
            'number': item.get('issue', ''),
            'pages': item.get('page', ''),
            'year': str(date_issued['date-parts'][0][0]),
            'doi': item.get('DOI', ''),
            'editor': ' and '.join([
                e.get('family', '') + ', ' + e.get('given', '')
                for e in item.get('editor', [])
            ]),
            'publisher': item.get('publisher', ''),
            'author': ' and '.join([
                a.get('family', '') + ', ' + a.get('given', '')
                for a in item.get('author', [])
            ])
        }

        if item['type'] == 'journal-article':
            bibtex_entry['journal'] = item.get('container-title', [''])[0]
        elif item['type'] == 'book-chapter':
            bibtex_entry['booktitle'] = item.get('container-title', [''])[0]

        append_bibfile(OUTPUT_BIBFILE_PATH, bibtex_entry)

        return self._paste(index)

    def _paste_pubmed(self, index):
        pmart = self.current_results_pmart[index]

        pubdate = pmart.publication_date
        if isinstance(pubdate, str):
            pubdate = dateutil.parser.parse(pubdate)

        bibtex_entry = {
            'id': self.current_results_keys[index],
            'type': 'article',

            'title': pmart.title,
            'year': str(pubdate.year),
            'doi': pmart.doi,
            'author': ' and '.join([
                (a.get('lastname') or '')
                + ', '
                + (a.get('initials') or '')
                + ' '
                + (a.get('firstname') or '')
                for a in pmart.authors
            ])
        }
        if isinstance(pmart, PubMedArticle):
            bibtex_entry['volume'] = pmart.volume
            bibtex_entry['number'] = pmart.issue
            bibtex_entry['pages'] = pmart.pages
            bibtex_entry['journal'] = pmart.journal
            bibtex_entry['keywords'] = pmart.keywords
        elif isinstance(pmart, PubMedBookArticle):
            bibtex_entry['type'] = 'incollection'
            bibtex_entry['booktitle'] = pmart.collection_title


        append_bibfile(OUTPUT_BIBFILE_PATH, bibtex_entry)
        return self._paste(index)

    def _paste_chemrxiv(self, index):
        id = self.current_results_keys[index]

        r = requests.get(
            "https://api.figshare.com/v2/articles/{id}".format(**locals()),
        )

        r.raise_for_status()

        article = r.json()

        pubdate = article["published_date"]
        pubdate = dateutil.parser.parse(pubdate)
        year = pubdate.year

        citekey = (
            ''.join(str(article["authors"][0].get('full_name', '')).split())
            + str(year)
        )
        citekey = unicodedata.normalize('NFKD', citekey)
        citekey = ''.join(
            c
            for c in citekey
            if c in
                'abcdefghijklmnopqrstuvwxyz'
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                '0123456789-_'
        )

        docs = documents()
        citekeys = set([doc.get('id') for doc in docs])
        citekey_suffix = 'a' if citekey in citekeys else ''
        while citekey + citekey_suffix in citekeys:
            citekey_suffix = chr(ord(citekey_suffix) + 1)
        citekey = citekey + citekey_suffix

        doi = article["doi"]

        bibtex_entry = {
            'id': citekey,
            'type': 'unpublished',

            'title': article["title"],
            'year': str(pubdate.year),
            'doi': doi,
            'author': ' and '.join([
                author.get('full_name') for author in article["authors"]
            ]),
            'note': 'ChemRxiv. Preprint. \\url{{https://doi.org/{}}}'.format(doi),
            'keywords': article["tags"]
        }

        self.current_results_keys[index] = citekey
        append_bibfile(OUTPUT_BIBFILE_PATH, bibtex_entry)
        return self._paste(index)


class CiterCompleteCitationEventListener(sublime_plugin.EventListener):

    """docstring for CiterCompleteCitationEventListener"""

    def on_query_completions(self, view, prefix, loc):
        refresh_settings()
        in_scope = any(
            view.match_selector(loc[0], scope)
            for scope in COMPLETIONS_SCOPES
        )
        ex_scope = any(
            view.match_selector(loc[0], scope)
            for scope in EXCLUDED_SCOPES
        )

        if ENABLE_COMPLETIONS and in_scope and not ex_scope:
            if SEARCH_COMPLETIONS:
                point = loc[0]
                prefix_ext_region = view.line(point)
                prefix_ext_region.b = point
                prefix_ext = view.substr(prefix_ext_region)

                if re.match(CITATION_RE, prefix_ext):
                    searcher = CiterSearchCommand(view)
                    searcher.run_keyonly(None)
            else:
                load_yamlbib_path(view)

                search = prefix.replace('@', '').lower()

                results = [
                    [key, key]
                    for key in citekeys_list()
                    if search in key.lower()
                ]

                if EXCLUDE and len(results) > 0:
                    return (results, sublime.INHIBIT_WORD_COMPLETIONS)
                else:
                    return results


class CiterCombineCitationsCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        refresh_settings()
        lstpos = self.view.find_all(r'\]\[')
        for i, pos in reversed(list(enumerate(lstpos))):
            self.view.replace(edit, pos, r'; ')
