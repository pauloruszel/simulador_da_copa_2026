from src.cli_args import parse_args


def test_cli_args_resolves_team_alias_and_all_teams():
    args = parse_args(["--team", "Brasil", "--all-teams"])

    assert args.team == "Brazil"
    assert args.global_report is True
