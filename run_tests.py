#!/usr/bin/env python3
"""
Runner de testes standalone — substitui pytest quando indisponível.
Importa cada arquivo de teste, chama funções que começam com 'test_'.
"""
from __future__ import annotations
import importlib.util
import sys
import traceback
import time
from pathlib import Path


def load_test_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_file(path: Path) -> tuple[int, int, list[str]]:
    passed = failed = 0
    errors = []
    try:
        module = load_test_module(path)
    except Exception as exc:
        errors.append(f"  IMPORT ERROR {path.name}: {exc}")
        return 0, 1, errors

    test_fns = [(name, fn) for name, fn in vars(module).items()
                if name.startswith("test_") and callable(fn)]

    for name, fn in test_fns:
        try:
            # Inspeciona assinatura — se precisa de tmp_path, cria pasta temp
            import inspect, tempfile
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            if "tmp_path" in params:
                with tempfile.TemporaryDirectory() as td:
                    fn(tmp_path=Path(td))
            else:
                fn()
            passed += 1
            print(f"  ✓ {name}")
        except Exception as exc:
            failed += 1
            tb = traceback.format_exc()
            errors.append(f"  ✗ {name}\n{tb}")
            print(f"  ✗ {name}: {exc}")
    return passed, failed, errors


def main(pattern: str = "test_*.py") -> int:
    tests_dir = Path(__file__).parent / "tests"
    files = sorted(tests_dir.glob(pattern))

    # Apenas novos arquivos se não explicitado
    target_files = [
        "test_market_anchor.py",
        "test_market_mode_cli.py",
        "test_market_comparison_full.py",
        "test_command_runner_market.py",
    ]
    if "--all" in sys.argv:
        target_files = [f.name for f in files]
    elif len(sys.argv) > 1 and sys.argv[1] != "--all":
        target_files = [sys.argv[1]]

    files_to_run = [tests_dir / f for f in target_files if (tests_dir / f).exists()]
    if not files_to_run:
        print("Nenhum arquivo de teste encontrado.")
        return 1

    total_passed = total_failed = 0
    all_errors = []
    start = time.time()

    for path in files_to_run:
        print(f"\n── {path.name} ──")
        p, f, errs = run_file(path)
        total_passed += p
        total_failed += f
        all_errors.extend(errs)

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"{'PASSOU' if total_failed == 0 else 'FALHOU'} — {total_passed} passaram, {total_failed} falharam em {elapsed:.2f}s")
    if all_errors:
        print("\nDetalhes dos erros:")
        for err in all_errors:
            print(err)
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
