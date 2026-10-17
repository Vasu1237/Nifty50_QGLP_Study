"""Run the Nifty 50 study pipeline in order (all downloads cached)."""
import subprocess
import sys
from pathlib import Path

here = Path(__file__).parent
for s in ["s01_membership", "s02_prices", "s02b_jump_review", "s02c_demerger_adjust", "s03_fundamentals", "s04_panel", "s05_dictionary_quality", "s06_prowess_load", "s07_panel_prowess", "s08_analysis", "s09_benchmark_uti", "s12_benchmark_avg", "s10_sharpe_uti", "s11_subperiod"]:
    print(f"=== {s}")
    if subprocess.run([sys.executable, str(here / f"{s}.py")], cwd=here).returncode:
        sys.exit(f"{s} failed")
