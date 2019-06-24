from collections import namedtuple
from itertools import combinations
from pathlib import Path
from typing import Tuple

from pyxdameraulevenshtein import damerau_levenshtein_distance as distance

from analysis.PluginBase import AnalysisBasePlugin

from ..internal.meta import unbinding, get_meta, DB

QUERIES = get_meta()


class AnalysisPlugin(AnalysisBasePlugin):
    '''
    lookup vulnerabilities from CVE feeds using ID from CPE dictionary
    '''
    NAME = 'cve_lookup'
    DESCRIPTION = 'lookup CVE vulnerabilities'
    MIME_BLACKLIST = ['audio', 'filesystem', 'image', 'video']
    DEPENDENCIES = ['software_components']
    VERSION = '0.0.1'
    SOFTWARE_SPECS = None

    def __init__(self, plugin_administrator, config=None, recursive=True):
        super().__init__(plugin_administrator, config=config, recursive=recursive, plugin_path=__file__)

    def process_object(self, file_object):
        cves = dict()
        for component in file_object.processed_analysis['software_components']['summary']:
            product, version = self._split_component(component)
            cves[component] = init_lookup(product_name=product, requested_version=version)

        cves['summary'] = list({cve for cve in [matches for matches in cves.values()]})
        file_object.processed_analysis[self.NAME] = cves

        return file_object

    @staticmethod
    def _split_component(component: str) -> Tuple[str, str]:
        '''
        take a software component string and split it into product and version
        if the number of split values is greater than 2, assume that all elements up to the second to last
        form the product string while the last element is the version string
        :param component: contains product name and product version
        :return: a tuple containing product name and product version
        '''
        component_parts = component.split('')
        return component_parts if len(component_parts) == 2 else ''.join(component_parts[:-2]), component_parts[-1]


def generate_search_terms(product_component: str) -> list:
    '''
    generates forward combinations of search terms concatenated by underscores and unbinds version string
    to conform to the CPE naming specification
    :param product_component: contains product name from software components' summary
    :return: tuple of list containing product search terms and the unbound version string
    '''
    product_terms = product_component.split()
    product_search_terms = ['_'.join(product_terms[i:j]).lower() for i, j in
                            combinations(range(len(product_terms) + 1), 2)]
    product_search_terms = unbinding(product_search_terms)

    return product_search_terms


def cpe_matching(db=None, product_search_terms: list = None, input_version: str = None) \
        -> tuple:
    '''
    matches CPE entries using generated search terms by comparing the vendor and product with the
    help of the damerau-levenshtein algorithm which calculates the string distance between two strings.
    The best fitting CPE entry is returned.
    :param db: contains hook to database object
    :param product_search_terms: contain all generated product search terms
    :param input_version: contains unbound version from software components' summary
    :return: tuple containing vendor name, product name and product version of best fit from CPE dictionary
    '''
    cpe_candidates = list()
    for vendor, product, version in list(db.select_query(QUERIES['sqlite_queries']['cpe_lookup'])):
        for product_term in product_search_terms:
            if distance(product_term, product) < 3:
                cpe_candidates.append((vendor, product, version))
                break

    cpe_candidates.sort(key=lambda v: distance(v[2], input_version))

    return cpe_candidates[0]


def cve_cpe_search(db=None, matched_product: namedtuple = None) -> list:
    '''
    uses the best fitting CPE entry to look for CPE entries in the CVE feeds comparing vendor, product and version
    with the help of the damerau-levenshtein algorithm. A list of CVE ids is returned.
    :param db: contains hook to database object
    :param matched_product: dataclass containing vendor- and product name as well as the version number
    :return: list containing CVE candidates for corresponding product
    '''
    cve_candidates = list()
    for cve_id, vendor, product, version in list(db.select_query(QUERIES['sqlite_queries']['cve_lookup'])):
        if distance(matched_product.vendor_name, vendor) < 3:
            if distance(matched_product.product_name, product) < 3:
                if matched_product.version_number in version or version == 'ANY' or version == 'NA':
                    cve_candidates.append(cve_id)

    cve_candidates = list(set(cve_candidates))
    return cve_candidates


def find_product_summary(vendor_product_distance: int, product_range: list, product_terms: list) -> bool:
    '''
    helper function that matches the product search term with words in the CVE summary after the product term has been
    found.
    :param vendor_product_distance: specifies the maximum distance found vendor and product are allowed to be
    :param product_range: contains part of the summary starting at the index of the found vendor term
    :param product_terms: contains the generated product terms
    :returns if a product term corresponding to a earlier found vendor terms is found in a short distance
    '''
    first_product_term = product_terms[0]
    for candidate in range(vendor_product_distance):
        if distance(first_product_term, product_range[candidate]) < 3:
            if len(product_terms) == 1:
                return True
            if len(product_terms) > 1:
                p_idx = 1
                for term in product_range[1:]:
                    if not distance(term, product_range[candidate+p_idx]) < 3:
                        return False
                    p_idx += 1
                return True

    return False


def cve_summary_search(db=None, matched_product: namedtuple = None) -> list:
    '''
    matches vendor and product search terms in the CVE summary
    :param db: contains hook to database object
    :param matched_product: dataclass containing vendor- and product name as well as the version number
    :return list containing CVE candidates found searching through CVE summaries
    '''
    cve_summary_candidates = list()
    # if product has matched, set True
    match = False
    vendor = matched_product.vendor_name.split('_')
    product = matched_product.product_name.split('_')

    for cve_id, summary in list(db.select_query(QUERIES['sqlite_queries']['summary_lookup'])):
        words = summary.split(' ')
        for idx, word in enumerate(words):
            word = word.lower()
            # a range in which the product term is allowed to come after the vendor term
            # for it not to be a false positive
            if match:
                break
            if distance(vendor[0], word) < 3 and len(words[idx + 2:]) >= len(product):
                vendor_product_distance = min(3, len(words[idx + 2:]))
                match = find_product_summary(vendor_product_distance, words[idx + 2:], product)
                if match:
                    cve_summary_candidates.append(cve_id)
                    match = False

    return cve_summary_candidates


def init_lookup(product_name: str, requested_version: str) -> list:
    '''
    gets search terms and initiates functions to find the vulnerabilities for the search terms
    :param product_name: product name from software components' summary
    :param requested_version: version from software components' summary
    :return list containing CVE candidates found with vendor -, product name and version from CPE dictionary
    '''
    Product = namedtuple('Product', 'vendor_name product_name version_number')
    with DB(str(Path(__file__).parent.parent) + '/internal/cpe_cve.db') as db:
        product_terms, version = generate_search_terms(product_name), unbinding([requested_version])
        vendor, product, version = cpe_matching(db, product_terms, version)
        matched_product = Product(vendor, product, version)
        cve_candidates = cve_cpe_search(db, matched_product)
        summary_can = cve_summary_search(db, matched_product)
        cve_candidates.extend(summary_can)

    return cve_candidates