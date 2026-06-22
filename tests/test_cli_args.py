from src.cli_args import parse_args


def test_cli_args_resolves_team_alias_and_all_teams():
    args = parse_args(["--team", "Brasil", "--all-teams"])

    assert args.team == "Brazil"
    assert args.global_report is True


def test_cli_accepts_odds_workflow():
    args = parse_args(["--workflow", "odds", "--all-teams", "--simulations", "1000", "--seed", "42"])

    assert args.workflow == "odds"
    assert args.global_report is True
    assert args.simulations == 1000
    assert args.seed == 42
