import sys
from os import remove
from pathlib import Path

import pytest

from test.common_helper import TEST_FW, get_config_for_testing

try:
    from ..code import vuln_lookup_plugin as lookup
    from ..internal.database_interface import DatabaseInterface
    from ..internal.helper_functions import unbind
except ImportError:
    ROOT = Path(__file__).parent.parent
    sys.path.extend([str(ROOT / 'code'), str(ROOT / 'internal')])
    import vuln_lookup_plugin as lookup
    from database_interface import DatabaseInterface
    from helper_functions import unbind


# pylint: disable=redefined-outer-name

USER_INPUT = {'vendor': 'Microsoft', 'product': 'Windows 7', 'version': '1.2.5'}

MATCHED_CPE = [
    lookup.PRODUCT('microsoft', 'windows_8', '1\\.2\\.5'),
    lookup.PRODUCT('microsoft', 'windows_7', '1\\.3\\.1'),
    lookup.PRODUCT('mircosof', 'windows_7', '0\\.7')
]
MATCHED_CVE = ['CVE-1234-0010', 'CVE-1234-0011']
CPE_CVE_OUTPUT = [('CVE-1234-0008', 'microsoft', 'server_2013', '2013'),
                  ('CVE-1234-0009', 'mircosof', 'windows_7', '0\\.7'),
                  ('CVE-1234-0010', 'microsoft', 'windows_8', '1\\.2\\.5'),
                  ('CVE-1234-0011', 'microsoft', 'windows_7', '1\\.3\\.1'),
                  ('CVE-1234-0012', 'linux', 'linux_kernel', '2\\.2.\\3')]

MATCHED_SUMMARY = ['CVE-1234-0005', 'CVE-1234-0006', 'CVE-1234-0007']
SUMMARY_OUTPUT = [('CVE-1234-0001', 'Attacker gains remote access'),
                  ('CVE-1234-0002', 'Attacker gains remote access to microsoft windows'),
                  ('CVE-1234-0003', 'Attacker gains remote access to microsoft server 2018'),
                  ('CVE-1234-0004', 'Attacker gains remote access to microsoft windows 2018'),
                  ('CVE-1234-0005', 'Attacker gains remote access to microsoft windows 8'),
                  ('CVE-1234-0006', 'Attacker gains remote access to microsoft windows 7'),
                  ('CVE-1234-0007', 'Attacker gains remote access to microsoft corporation windows 7')]

PRODUCT_SEARCH_TERMS = ['windows', 'windows_7']
VERSION_SEARCH_TERM = '1\\.2\\.5'
CPE_DATABASE_OUTPUT = [('microsoft', 'server_2013', '2013'),
                       ('mircosof', 'windows_7', '0\\.7'),
                       ('microsoft', 'windows_8', '1\\.2\\.5'),
                       ('microsoft', 'windows_7', '1\\.3\\.1'),
                       ('linux', 'linux_kernel', '2\\.2.\\3')]

SUMMARY_INPUT = ''

SORT_CPE_MATCHES_OUTPUT = lookup.PRODUCT('microsoft', 'windows_8', '1\\.2\\.5')

SOFTWARE_COMPONENTS_ANALYSIS_RESULT = {
    'dnsmasq': {
        'meta': {
            'software_name': 'Dnsmasq',
            'version': ['2.40']
        }
    },
    'OpenSSL': {
        'matches': True,
        'meta': {
            'description': 'SSL library',
            'open_source': True,
            'software_name': 'OpenSSL',
            'version': [''],
            'website': 'https://www.openssl.org'
        },
        'rule': 'OpenSSL',
        'strings': [[7194, '$a', 'T1BFTlNTTA==']]
    },
    'analysis_date': 1563453634.37708,
    'plugin_version': '0.3.2',
    'summary': [
        'OpenSSL ',
        'Dnsmasq 2.40'
    ],
    'system_version': '3.7.1_1560435912',
}


@pytest.fixture(scope='module', autouse=True)
def setup() -> None:
    yield None
    try:
        remove('test.db')
    except OSError:
        pass


def test_generate_search_terms():
    assert PRODUCT_SEARCH_TERMS == unbind(lookup.generate_search_terms('windows 7'))


@pytest.mark.parametrize('version, expected_output', [
    ('11\\.00\\.00', True),
    ('1\\.0\\.0', True),
    ('1\\.0', True),
    ('1', False),
    ('\\.1\\.0', False),
    ('1\\.0\\.', False),
    ('1\\.\\.0', False),
    ('\\.1\\.0\\.', False),
])
def test_is_valid_dotted_version(version, expected_output):
    assert lookup.is_valid_dotted_version(version) == expected_output


@pytest.mark.parametrize('version, index, expected', [('1\\.2\\.3', 0, '1'), ('1\\.2\\.3\\.2a', -1, '2a')])
def test_get_version_index(version, index, expected):
    assert lookup.get_version_index(version=version, index=index) == expected


@pytest.mark.parametrize('target_values, expected', [
    ([lookup.PRODUCT('abc', 'def', '1\\.2\\.3'), lookup.PRODUCT('abc', 'def', '4\\.5\\.6')], ['1\\.2\\.3', '4\\.5\\.6'])
])
def test_get_version_numbers(target_values, expected):
    assert lookup.get_version_numbers(target_values=target_values) == expected


@pytest.mark.parametrize('target_values, search_word, expected', [
    (['1\\.2\\.3', '2\\.2\\.2', '4\\.5\\.6'], '2\\.2\\.2', ['1\\.2\\.3', '4\\.5\\.6']),
    (['1\\.1\\.1', '1\\.2\\.3', '4\\.5\\.6'], '1\\.1\\.1', ['1\\.2\\.3']),
    (['1\\.2\\.3', '4\\.5\\.6', '7\\.8\\.9'], '7\\.8\\.9', ['4\\.5\\.6'])
])
def test_get_closest_matches(target_values, search_word, expected):
    assert lookup.get_closest_matches(target_values=target_values, search_word=search_word) == expected


def test_find_matching_cpe_product():
    assert SORT_CPE_MATCHES_OUTPUT == lookup.find_matching_cpe_product(MATCHED_CPE, VERSION_SEARCH_TERM)


@pytest.mark.parametrize('term, expected_output', [
    ('mircosoft', True),
    ('microsof', True),
    ('microso', True),
    ('ircosof', False),
])
def test_terms_match(term, expected_output):
    assert lookup.terms_match(term, 'microsoft') == expected_output


@pytest.mark.parametrize('word_list, remaining_words, expected_output', [
    (['aaaa', 'bbbb', 'cccc', 'dddd', 'eeee', 'ffff', 'gggg'], ['cccc', 'dddd', 'eeee'], True),
    (['abcde', 'ghkl'], ['abcdef', 'ghijkl'], True),
    (['abcde', 'ghkl'], ['abcdef', 'ghijklmnop'], False)
])
def test_word_is_in_wordlist(word_list, remaining_words, expected_output):
    assert lookup.word_is_in_wordlist(word_list, remaining_words) == expected_output


@pytest.mark.parametrize('word_list, remaining_words, expected_output', [
    (['abcde', 'ghkl'], ['abcdef', 'ghijkl'], True),
    (['abcde', 'ghkl'], ['abcdef', 'ghijklmnop'], False)
])
def test_remaining_words_present(word_list, remaining_words, expected_output):
    assert lookup.remaining_words_present(word_list, remaining_words) == expected_output


@pytest.mark.parametrize('word_list, expected_output', [
    (['bla', 'bla', 'microsoft', 'windows', '8', 'bla'], True),
    (['bla', 'bla', 'microsoft', 'windows'], False),
    (['bla', 'bla', 'mirosoft', 'windos', '7', 'bla'], True),
    (['bla', 'bla', 'microsoft', 'corporation', 'windows', '8', 'bla'], True),
    (['bla', 'bla', 'microsoft', 'corporation', 'corp', 'inc', 'windows', '8', 'bla'], False),
    (['bla', 'bla', 'microsoft', 'windows', '8'], True),
    (['bla', 'bla', 'microsoft', 'windows', 'home', '8', 'bla'], False),
])
def test_product_is_in_wordlist(word_list, expected_output):
    assert lookup.product_is_in_wordlist(SORT_CPE_MATCHES_OUTPUT, word_list) == expected_output


@pytest.mark.parametrize('word_list, sequence, expected_result', [
    (['', '', ''], ['', ''], True),
    (['', ''], ['', '', ''], False),
    (['', ''], ['', ''], True)
])
def test_wordlist_longer_than_sequence(word_list, sequence, expected_result):
    assert lookup.wordlist_longer_than_sequence(word_list, sequence) == expected_result


def test_match_cpe(monkeypatch):
    with monkeypatch.context() as monkey:
        monkey.setattr(DatabaseInterface, 'select_query', lambda *_, **__: CPE_DATABASE_OUTPUT)
        actual_match = list(lookup.match_cpe(DatabaseInterface, PRODUCT_SEARCH_TERMS))
        assert all(entry in actual_match for entry in MATCHED_CPE)


def test_search_cve(monkeypatch):
    with monkeypatch.context() as monkey:
        monkey.setattr(DatabaseInterface, 'select_query', lambda *_, **__: CPE_CVE_OUTPUT)
        MATCHED_CVE.sort()
        actual_match = list(lookup.search_cve(DatabaseInterface, SORT_CPE_MATCHES_OUTPUT))
        actual_match.sort()
        assert MATCHED_CVE == actual_match


def test_search_cve_summary(monkeypatch):
    with monkeypatch.context() as monkey:
        monkey.setattr(DatabaseInterface, 'select_query', lambda *_, **__: SUMMARY_OUTPUT)
        MATCHED_SUMMARY.sort()
        actual_match = list(lookup.search_cve_summary(DatabaseInterface, SORT_CPE_MATCHES_OUTPUT))
        actual_match.sort()
        assert MATCHED_SUMMARY == actual_match


class MockAdmin:
    def register_plugin(self, name, administrator):
        pass


@pytest.fixture(scope='function')
def test_config():
    return get_config_for_testing()


@pytest.fixture(scope='function')
def stub_plugin(test_config, monkeypatch):
    monkeypatch.setattr('plugins.base.BasePlugin._sync_view', lambda self, plugin_path: None)
    return lookup.AnalysisPlugin(MockAdmin(), test_config, offline_testing=True)


def test_process_object(stub_plugin):
    TEST_FW.processed_analysis['software_components'] = SOFTWARE_COMPONENTS_ANALYSIS_RESULT
    result = stub_plugin.process_object(TEST_FW).processed_analysis['cve_lookup']
    assert 'CVE-2017-14494' in result['summary']