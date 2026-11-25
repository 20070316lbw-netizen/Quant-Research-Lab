"""S2 前视检查。输入来自 01_fetch_and_clean.py 与 03_spread.py, 在临时目录运行扰动实验"""
from pathlib import Path
from shutil import copytree
import subprocess
import sys
from tempfile import TemporaryDirectory

import pandas as pd

root = Path.cwd()
with TemporaryDirectory() as folder:
    work = Path(folder)
    for name in ["configs", "data/clean"]:
        copytree(root / name, work / name)
    path = work / "data/clean/quarterly.csv"
    panel = pd.read_csv(path)
    future = panel.quarter > "1989Q4"
    panel.loc[future, "spread"] += 1
    panel.loc[future, "recession"] = 1 - panel.loc[future, "recession"]
    panel.to_csv(path, index=False)
    subprocess.run([sys.executable, root / "scripts/03_spread.py"], cwd=work,
                   check=True, stdout=subprocess.DEVNULL)
    original = pd.read_csv(root / "outputs/forecasts.csv")
    changed = pd.read_csv(work / "outputs/forecasts.csv")
    earlier = original.origin <= "1989Q4"
    pd.testing.assert_frame_equal(original.loc[earlier, ["h","origin","target","probability"]],
                                  changed.loc[earlier, ["h","origin","target","probability"]],
                                  atol=1e-10, rtol=0)
    assert (original.last_label <= original.origin).all()
    assert original.groupby("h").size().tolist() == [97] * 4
    print(f"未来观测扰动后, {earlier.sum()} 条历史预测保持一致")
