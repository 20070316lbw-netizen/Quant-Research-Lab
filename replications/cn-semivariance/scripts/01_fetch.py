"""S1 数据获取: 按 configs/pilot.yaml 抽取固定快照的五分钟文件"""

from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text())
raw = ROOT / "data/raw"
raw.mkdir(exist_ok=True, parents=True)
tickers = chain.from_iterable(cfg["industries"].values())
base = f"https://huggingface.co/datasets/{cfg['provider']}/resolve/{cfg['revision']}/"


def _fetch(job: tuple[str, str]) -> None:
    """按远端路径和本地文件名下载单个原始文件, 上游为 YAML 指定的不可变快照"""
    source, name = job
    path = raw / name
    if path.exists():
        return
    for attempt in range(3):
        try:
            with urlopen(base + quote(source), timeout=60) as response:
                content = response.read()
            path.with_suffix(".part").write_bytes(content)
            path.with_suffix(".part").replace(path)
            return
        except HTTPError as error:
            if error.code == 404 and name.endswith(".csv"):
                return
            if attempt == 2:
                raise
        except (TimeoutError, URLError):
            if attempt == 2:
                raise
        sleep(2**attempt)


if __name__ == "__main__":
    jobs = []
    for ticker in tickers:
        for year in cfg["years"]:
            jobs.append(
                (f"A股分钟/2000-2024/{year}/5分钟/{ticker}.csv", f"{ticker}-{year}.csv")
            )
    with ThreadPoolExecutor(10) as pool:
        list(pool.map(_fetch, jobs))
