"""用冻结的美股行情检验 Ant-Transformer 的月度选股信号"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research_lab.data import (
    load_calendar,
    load_prices,
    load_universe_panel,
    validate_panel,
)
from quant_research_lab.experiments import config_sha256, load_experiment_config
from quant_research_lab.stats import (
    adjust_pvalues,
    compute_ic_series,
    deflated_sharpe_ratio,
    performance_summary,
    quantile_portfolio_returns,
    standardize_cs,
    summarize_ic,
    winsorize_cs,
)

CONFIG = Path("configs/eq-cs-002_ant_transformer.yaml")
VARIANTS = {
    "vanilla": (False, False),
    "cross_only": (True, False),
    "gate_only": (False, True),
    "ant_full": (True, True),
}


def _monthly_features(close, volume, months, eligible):
    daily_returns = close.div(close.shift(1)) - 1.0
    features = {
        "mom_20d": close.div(close.shift(20)) - 1.0,
        "mom_60d": close.div(close.shift(60)) - 1.0,
        "mom_12m_1m": close.shift(21).div(close.shift(252)) - 1.0,
        "vol_60d": daily_returns.rolling(60, min_periods=55).std(),
        "log_volume_ratio": np.log(
            volume.rolling(20, min_periods=18).mean().div(
                volume.rolling(120, min_periods=105).mean()
            ).where(lambda ratio: ratio > 0.0)
        ),
    }
    panel = pd.DataFrame(
        {name: values.loc[months].stack().reindex(eligible) for name, values in features.items()}
    ).replace([np.inf, -np.inf], np.nan).dropna().astype("float64").sort_index()
    validate_panel(panel, name="monthly price and volume features")
    return pd.DataFrame({
        name: standardize_cs(winsorize_cs(signal, method="quantile", lower=0.01, upper=0.99))
        for name, signal in panel.items()
    }).dropna()


def _windows(panel, months, tickers, length):
    panel_grid = pd.MultiIndex.from_product([months, tickers], names=["date", "ticker"])
    grid = panel.reindex(panel_grid).to_numpy(dtype=np.float32).reshape(
        len(months), len(tickers), len(panel.columns)
    )
    windows = np.lib.stride_tricks.sliding_window_view(grid, length, axis=0)
    windows = windows.transpose(0, 1, 3, 2)
    complete = np.isfinite(windows).all(axis=(2, 3))
    return (
        windows[complete],
        panel_grid[(length - 1) * len(tickers):][complete.ravel()],
    )


def _forward_labels(adjusted_open, adjusted_close, index, calendar, lag):
    months = calendar.to_series().groupby(calendar.to_period("M")).last()
    month_start = calendar.to_series().groupby(calendar.to_period("M")).first()
    observed_close = adjusted_close.ffill().shift(1)
    parts = []
    for signal_date, group in pd.Series(index.get_level_values("ticker"), index=index).groupby(level="date"):
        signal_month = signal_date.to_period("M")
        if signal_month + 2 not in month_start.index:
            continue
        assert signal_date == months.loc[signal_month]
        entry_date = calendar[calendar.get_loc(month_start.loc[signal_month + 1]) + lag - 1]
        exit_date = calendar[calendar.get_loc(month_start.loc[signal_month + 2]) + lag - 1]
        tickers = group.to_numpy()
        entry = adjusted_open.loc[entry_date, tickers].to_numpy()
        exit_open = adjusted_open.loc[exit_date, tickers].to_numpy()
        last_mark = observed_close.loc[exit_date, tickers].to_numpy()
        no_entry = ~np.isfinite(entry)
        proxy_exit = ~np.isfinite(exit_open) & ~no_entry
        exit_price = np.where(proxy_exit, last_mark, exit_open)
        ret = np.zeros(len(tickers))
        np.divide(exit_price, entry, out=ret, where=~no_entry)
        ret[~no_entry] -= 1.0
        parts.append(pd.DataFrame(
            {"return": ret, "exit_date": exit_date, "no_entry": no_entry, "proxy_exit": proxy_exit},
            index=group.index,
        ))
    result = pd.concat(parts).reindex(index)
    validate_panel(result[["return"]], name="forward monthly returns")
    return result


def _prepare(cfg):
    params = cfg.model.params
    bounds = (cfg.data.start_date, cfg.data.end_date)
    db = Path(cfg.data.db_path)
    calendar = load_calendar(*bounds, db_path=db)
    months = pd.DatetimeIndex(
        calendar.to_series().groupby(calendar.to_period("M")).last(), name="date"
    )
    eligible = load_universe_panel(*bounds, columns=("cik",), db_path=db).index
    eligible = eligible[eligible.get_level_values("date").isin(months)]
    tickers = eligible.get_level_values("ticker").unique().sort_values()
    raw = load_prices(*bounds, sp500_only=False, tickers=tickers.to_list(), db_path=db,
                      columns=("open", "close", "adj_close", "volume"))
    ns = {"index": "date", "columns": "ticker"}
    panels = {
        column: raw[column].unstack().reindex(index=calendar, columns=tickers).rename_axis(**ns)
        for column in ("open", "close", "adj_close", "volume")
    }
    adj = panels["adj_close"].where(panels["adj_close"] > 0)
    close = panels["close"].where(panels["close"] > 0)
    adjusted_open = panels["open"].where(panels["open"] > 0).mul(adj.div(close))
    features = _monthly_features(adj, panels["volume"], months, eligible)
    x, idx = _windows(features, months, tickers, params["seq_len"])
    cap = idx.get_level_values("date") <= pd.Timestamp(params["last_signal"])
    x, idx = x[cap], idx[cap]
    labels = _forward_labels(adjusted_open, adj, idx, calendar, cfg.execution.signal_lag_days)
    assert labels["return"].notna().all() and labels["exit_date"].notna().all()
    return x, labels, features.columns.to_list()


def _predict(model, features, batch_size):
    import torch

    model.eval()
    with torch.inference_mode():
        return np.concatenate([
            model(batch)[0].flatten().numpy()
            for batch in torch.from_numpy(features).split(batch_size)
        ]).astype("float64")


def _fit_ant(cross, gate, seed, params, x, labels, target, train, val, test, checkpoint):
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    from ant_transformer.config import AntConfig
    from ant_transformer.model.ant import AntTransformer

    torch.manual_seed(seed)
    fields = ("d_model", "num_heads", "cross_layer_heads", "d_ff", "gate_hidden_dim", "dropout")
    config = AntConfig.from_dict({
        **{field: params[field] for field in fields},
        "input_dim": x.shape[-1],
        "seq_len": x.shape[1],
        "use_cross_layer": cross,
        "use_soft_gating": gate,
        "enable_layer_pruning": gate,
    })
    model = AntTransformer(config)
    train_data = TensorDataset(torch.from_numpy(x[train]), torch.from_numpy(target[train]))
    loader = DataLoader(train_data, batch_size=params["batch_size"], shuffle=True,
                        generator=torch.Generator().manual_seed(seed))
    optimizer = torch.optim.AdamW(model.parameters(), lr=params["lr"], weight_decay=0.01)
    loss_fn = nn.MSELoss()
    best, best_state = float("-inf"), None
    history = []
    val_truth = labels.loc[val, "return"]
    for epoch in range(1, params["epochs"] + 1):
        model.train()
        gate_sums = np.zeros(config.num_layers)
        for features, y in loader:
            optimizer.zero_grad(set_to_none=True)
            out, _, gates = model(features)
            gate_means = torch.stack([g.mean() for g in gates])
            loss = loss_fn(out.flatten(), y)
            if gate:
                loss = loss + params["gate_lambda"] * gate_means.mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            gate_sums += gate_means.detach().numpy() * len(y)
        scores = pd.Series(_predict(model, x[val], params["batch_size"]), index=val_truth.index)
        rank_ic = float(compute_ic_series(scores, val_truth).mean())
        history.append({"epoch": epoch, "validation_rank_ic": rank_ic,
                        "training_gate_means": (gate_sums / len(train_data)).tolist()})
        print(f"{checkpoint.stem} epoch {epoch} validation Rank IC {rank_ic:+.4f}", flush=True)
        if rank_ic > best:
            best = rank_ic
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
    if best_state is None:
        raise RuntimeError("No finite validation Rank IC")
    model.load_state_dict(best_state)
    torch.save({"config": config.to_dict(), "state_dict": best_state}, checkpoint)
    info = {"best_epoch": best_epoch, "parameters": model.count_parameters(), "history": history}
    return _predict(model, x[test], params["batch_size"]), info


def _rank_ensemble(seed_scores):
    return pd.concat(seed_scores, axis=1).groupby(level="date").rank(pct=True).mean(axis=1)


def _cost_turnover(signal, n_quantiles):
    date_groups = signal.groupby(level="date")
    ranks = date_groups.rank(method="average")
    sizes = date_groups.transform("size")
    buckets = ((ranks - 1.0) * n_quantiles // sizes).clip(upper=n_quantiles - 1)
    sides = (buckets.eq(n_quantiles - 1).astype(float) - buckets.eq(0).astype(float))
    side_sizes = sides.groupby([sides.index.get_level_values("date"), sides]).transform("size")
    targets = (0.5 * sides / side_sizes).unstack(fill_value=0.0)
    deltas = targets.diff()
    deltas.iloc[0] = targets.iloc[0]
    return deltas.abs().sum(axis=1)


def _audit(predictions, labels, cfg):
    truth = labels["return"]
    metrics, monthly = {}, {}
    rank_ic_by_model = {}
    for name, signal in predictions.items():
        rank_ic = compute_ic_series(signal, truth, method="spearman")
        rank_ic_by_model[name] = rank_ic
        qs, spread = quantile_portfolio_returns(
            signal, truth, n_quantiles=cfg.execution.long_short.n_quantiles,
            nw_lags=cfg.audit.nw_lags,
        )
        turnover = _cost_turnover(signal, cfg.execution.long_short.n_quantiles)
        gross = qs["long_short"] / 2.0
        costs = {
            str(bps): gross - (bps / 10000) * turnover
            for bps in cfg.execution.cost_bps_grid
        }
        net = costs[str(cfg.execution.cost_bps_default)]
        perf = performance_summary(net, periods_per_year=12)
        dsr = deflated_sharpe_ratio(net, n_trials=cfg.audit.n_trials, periods_per_year=12)
        metrics[name] = {
            "rank_ic": summarize_ic(rank_ic, nw_lags=cfg.audit.nw_lags).to_dict(),
            "pearson_ic": summarize_ic(compute_ic_series(signal, truth, method="pearson"),
                                       nw_lags=cfg.audit.nw_lags).to_dict(),
            "gross_full_spread": spread.to_dict(),
            "mean_turnover": float(turnover.mean()),
            "cost_sensitivity_mean": {bps: float(series.mean()) for bps, series in costs.items()},
            "net_performance": {k: v.to_dict() for k, v in perf.items()},
            "net_dsr": dsr.to_dict(),
        }
        monthly[name] = pd.DataFrame({
            "rank_ic": rank_ic, "gross": gross, "turnover": turnover, "net": net
        })
    tests = {name: row["rank_ic"]["p_value"] for name, row in metrics.items()}
    paired = {}
    for name in ("vanilla", "ridge"):
        delta = (rank_ic_by_model["ant_full"] - rank_ic_by_model[name]).rename("rank_ic_delta")
        result = summarize_ic(delta, nw_lags=cfg.audit.nw_lags).to_dict()
        paired[name] = result
        tests[f"ant_full_minus_{name}"] = result["p_value"]
    adjusted = adjust_pvalues(tests, method=cfg.audit.p_adjust_method)
    return metrics, paired, adjusted.to_dict(orient="index"), pd.concat(monthly, names=["model", "date"])


def _split(labels, cfg):
    dates = labels.index.get_level_values("date")
    train_end = pd.Timestamp(cfg.split.is_end_date)
    test_start = pd.Timestamp(cfg.split.oos_start_date)
    train = (dates <= train_end) & (labels["exit_date"].to_numpy() <= train_end)
    val_end = pd.Timestamp(cfg.model.params["validation_end"])
    val = (dates > train_end) & (dates <= val_end) & (labels["exit_date"].to_numpy() < test_start)
    test = dates >= test_start
    return train, val, test


def _main():
    import torch

    cfg = load_experiment_config(CONFIG)
    params = cfg.model.params
    torch.set_num_threads(params["threads"])
    output = cfg.run_output_dir()
    output.mkdir(parents=True, exist_ok=True)
    x, labels, features = _prepare(cfg)
    train, val, test = _split(labels, cfg)
    counts = {
        key: {"rows": int(mask.sum()),
              "months": int(labels.index[mask].get_level_values("date").nunique()),
              "first": str(labels.index[mask].get_level_values("date").min().date()),
              "last": str(labels.index[mask].get_level_values("date").max().date()),
              "no_entry": int(labels.loc[mask, "no_entry"].sum()),
              "proxy_exit": int(labels.loc[mask, "proxy_exit"].sum())}
        for key, mask in (("train", train), ("validation", val), ("test", test))
    }
    print(counts, flush=True)
    target = labels["return"].groupby(level="date").rank(pct=True).to_numpy(dtype=np.float32) * 2 - 1
    test_idx = labels.index[test]
    flat = x.reshape(len(x), -1).astype(np.float64)
    flat = np.column_stack([np.ones(len(x)), flat])
    design = flat[train]
    regularization = np.eye(design.shape[1]) * params["ridge_alpha"]
    regularization[0, 0] = 0.0
    ridge = np.linalg.solve(design.T @ design + regularization, design.T @ target[train])
    predictions = {
        "momentum": pd.Series(x[test, -1, features.index("mom_12m_1m")].astype(float), index=test_idx),
        "ridge": pd.Series(flat[test] @ ridge, index=test_idx),
    }
    runs = {}
    for name, (cross, gate) in VARIANTS.items():
        scores = []
        for seed in (cfg.meta.seed, params["second_seed"]):
            key = f"{name}_{seed}"
            pred, runs[key] = _fit_ant(
                cross, gate, seed, params, x, labels, target, train, val, test, output / f"{key}.pt"
            )
            scores.append(pd.Series(pred, index=test_idx))
        predictions[name] = _rank_ensemble(scores)
    metrics, paired, adjusted, monthly = _audit(predictions, labels.loc[test], cfg)
    summary = {
        "config_sha256": config_sha256(CONFIG), "dataset": cfg.data.dataset_version,
        "n_trials": cfg.audit.n_trials, "features": features, "split": counts,
        "ant_source": "bfbf5d3600d0e31e48f050c1e01aa6d09b629cd7",
        "lab_source": "2e47445a8a55694f1c7f20a88659160ccfbbc002",
        "runtime": {"torch": torch.__version__, "numpy": np.__version__, "pandas": pd.__version__},
        "models": metrics, "paired_ant_full_minus": paired, "holm": adjusted, "training_runs": runs,
    }
    def finite_json(value):
        if isinstance(value, dict):
            return {key: finite_json(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [finite_json(item) for item in value]
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value
    (output / "summary.json").write_text(
        json.dumps(finite_json(summary), ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n"
    )
    monthly.to_csv(output / "monthly_metrics.csv")
    print("Completed", output, flush=True)


if __name__ == "__main__":
    _main()
