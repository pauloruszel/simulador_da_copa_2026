from src.team_names import normalize_team_key, resolve_team_name


def test_resolve_team_name_in_english_and_pt_br():
    assert resolve_team_name("United States") == "United States"
    assert resolve_team_name("EUA") == "United States"
    assert resolve_team_name("Estados Unidos") == "United States"
    assert resolve_team_name("Brasil") == "Brazil"
    assert resolve_team_name("Marrocos") == "Morocco"


def test_normalize_team_key_removes_accents_and_case():
    assert normalize_team_key("  SUÍÇA ") == "suica"
    assert normalize_team_key("Bosnia-Herzegovina") == "bosnia herzegovina"

