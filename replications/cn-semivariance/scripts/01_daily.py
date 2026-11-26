"""S1: 提取社区 Qlib 复权日收盘和股票池, 保留调整价格字段"""

import shutil
import tarfile
from itertools import chain
from pathlib import Path
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
raw = ROOT / "data/raw"
raw.mkdir(exist_ok=True, parents=True)
cfg = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text())
archive = raw / "qlib_bin.tar.gz"
if not archive.exists():
    with (
        urlopen(cfg["qlib_release"], timeout=180) as src,
        archive.with_suffix(".part").open("wb") as dst,
    ):
        shutil.copyfileobj(src, dst)
    archive.with_suffix(".part").replace(archive)
wanted = {"calendars/day.txt": "day.txt", "instruments/csi300.txt": "csi300.txt"}
for ticker in chain.from_iterable(cfg["industries"].values()):
    wanted[f"features/{ticker}/adjclose.day.bin"] = f"{ticker}.bin"
with tarfile.open(archive, "r|gz") as tar:
    for member in tar:
        name = member.name.removeprefix("qlib_bin/")
        if name in wanted:
            (raw / wanted.pop(name)).write_bytes(tar.extractfile(member).read())
assert not wanted
