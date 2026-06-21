from src.external.wikipedia_scraper import WikipediaWorldCupScraper


def test_wikipedia_scraper_parses_finished_and_scheduled_matches():
    scraper = WikipediaWorldCupScraper()
    section = """
    <h3 id="Group_C">Group C</h3>
    <p>June&nbsp;13,&nbsp;2026&nbsp;(2026-06-13)</p>
    <p>6:00 p.m. UTC-4</p>
    <p><a>Brazil</a> <a>1–1</a> <a>Morocco</a></p>
    <p>[ Report 13 ]</p>
    <p>June&nbsp;24,&nbsp;2026&nbsp;(2026-06-24)</p>
    <p>6:00 p.m. UTC-4</p>
    <p><a>Scotland</a> <a>Match 49</a> <a>Brazil</a></p>
    """
    matches = scraper._parse_group(section, "C")
    assert matches[0]["home"] == "Brazil"
    assert matches[0]["away"] == "Morocco"
    assert matches[0]["home_score"] == 1
    assert matches[0]["away_score"] == 1
    assert matches[0]["status"] == "finished"
    assert matches[1]["status"] == "scheduled"
