import json
import datetime

from .helpers import getContent


class PubMedBookArticle(object):
    """ Data class that contains a PubMed article.
    """

    __slots__ = (
        "pubmed_id",
        "title",
        "abstract",
        "publication_date",
        "authors",
        "copyrights",
        "doi",
        "isbn",
        "language",
        "publication_type",
        "sections",
        "publisher",
        "publisher_location",
        "collection_title",
        "xml"
    )

    def __init__(self, xml_element=None, *args, **kwargs):
        """ Initialization of the object from XML or from parameters.
        """

        # If an XML element is provided, use it for initialization
        if xml_element is not None:
            self._initializeFromXML(xml_element=xml_element)

        # If no XML element was provided, try to parse the input parameters
        else:
            for field in self.__slots__:
                self.__setattr__(field, kwargs.get(field, None))

    def _extractPubMedId(self, xml_element) -> str:
        path = ".//ArticleId[@IdType='pubmed']"
        return getContent(element=xml_element, path=path)

    def _extractTitle(self, xml_element) -> str:
        path = ".//BookTitle"
        return getContent(element=xml_element, path=path)

    def _extractAbstract(self, xml_element) -> str:
        path = ".//AbstractText"
        return getContent(element=xml_element, path=path)

    def _extractCopyrights(self, xml_element) -> str:
        path = ".//CopyrightInformation"
        return getContent(element=xml_element, path=path)

    def _extractDoi(self, xml_element) -> str:
        path = ".//ArticleId[@IdType='doi']"
        return getContent(element=xml_element, path=path)

    def _extractIsbn(self, xml_element) -> str:
        path = ".//Isbn"
        return getContent(element=xml_element, path=path)

    def _extractLanguage(self, xml_element) -> str:
        path = ".//Language"
        return getContent(element=xml_element, path=path)

    def _extractPublicationType(self, xml_element) -> str:
        path = ".//PublicationType"
        return getContent(element=xml_element, path=path)

    def _extractPublicationDate(self, xml_element) -> str:
        path = ".//PubDate/Year"
        return getContent(element=xml_element, path=path)

    def _extractPublisher(self, xml_element) -> str:
        path = ".//Publisher/PublisherName"
        return getContent(element=xml_element, path=path)

    def _extractPublisherLocation(self, xml_element) -> str:
        path = ".//Publisher/PublisherLocation"
        return getContent(element=xml_element, path=path)

    def _extractCollectionTitle(self, xml_element) -> str:
        path = ".//CollectionTitle"
        return getContent(element=xml_element, path=path)

    def _extractAuthors(self, xml_element) -> list:
        return [
            {
                "collective": getContent(author, path=".//CollectiveName"),
                "lastname": getContent(element=author, path=".//LastName"),
                "firstname": getContent(element=author, path=".//ForeName"),
                "initials": getContent(element=author, path=".//Initials"),
            }
            for author in xml_element.findall(".//Author")
        ]

    def _extractSections(self, xml_element) -> list:
        return [
            {
                "title": getContent(section, path=".//SectionTitle"),
                "chapter": getContent(element=section, path=".//LocationLabel"),
            }
            for section in xml_element.findall(".//Section")
        ]

    def _initializeFromXML(self, xml_element) -> None:
        """ Helper method that parses an XML element into an article object.
        """

        # Parse the different fields of the article
        self.pubmed_id = self._extractPubMedId(xml_element)
        self.title = self._extractTitle(xml_element)
        self.abstract = self._extractAbstract(xml_element)
        self.copyrights = self._extractCopyrights(xml_element)
        self.doi = self._extractDoi(xml_element)
        self.isbn = self._extractIsbn(xml_element)
        self.language = self._extractLanguage(xml_element)
        self.publication_date = self._extractPublicationDate(xml_element)
        self.authors = self._extractAuthors(xml_element)
        self.publication_type = self._extractPublicationType(xml_element)
        self.publisher = self._extractPublisher(xml_element)
        self.publisher_location = self._extractPublisherLocation(xml_element)
        self.sections = self._extractSections(xml_element)
        self.collection_title = self._extractCollectionTitle(xml_element)
        self.xml = xml_element

    def toDict(self) -> dict:
        """ Helper method to convert the parsed information to a Python dict.
        """

        return {
            key: (self.__getattribute__(key) if hasattr(self, key) else None)
            for key in self.__slots__
        }

    def toJSON(self) -> str:
        """ Helper method for debugging, dumps the object as JSON string.
        """

        return json.dumps(
            {
                key: (value if not isinstance(value, datetime.date) else str(value))
                for key, value in self.toDict().items()
            },
            sort_keys=True,
            indent=4,
        )
