"""Cache-aware cost router.  All currency calculations use Decimal, not float."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Iterable
import argparse

getcontext().prec = 28
MILLION = Decimal("1000000")
D = Decimal


@dataclass(frozen=True)
class ModelPricing:
    name: str
    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal


MODEL_A = ModelPricing("Model A", D("5.00"), D("0.50"), D("20.00"))
MODEL_B = ModelPricing("Model B", D("1.00"), D("0.10"), D("5.00"))


@dataclass(frozen=True)
class Config:
    existing_context: int = 50_000
    new_input: int = 2_000
    expected_output: int = 1_000
    compacted_context: int = 12_000
    ttl_minutes: Decimal = D("5")
    keep_alive_interval_minutes: Decimal = D("4")
    keep_alive_new_input: int = 0
    keep_alive_output: int = 0
    compaction_output: int = 1_000
    warm_retry_probability: Decimal = D("0")
    compact_retry_probability: Decimal = D("0")
    switch_retry_probability: Decimal = D("0")


@dataclass(frozen=True)
class CostBreakdown:
    strategy: str
    model: str
    request_cost: Decimal
    maintenance_or_compaction_cost: Decimal
    total_cost: Decimal
    detail: str


def token_cost(tokens: int, price_per_million: Decimal) -> Decimal:
    return D(tokens) * price_per_million / MILLION


def request_cost(model: ModelPricing, *, cached_tokens: int = 0,
                 uncached_input_tokens: int = 0, output_tokens: int = 0) -> Decimal:
    """Price a prompt; cached input is billed, never treated as a free response cache."""
    return (token_cost(cached_tokens, model.cached_input_per_million)
            + token_cost(uncached_input_tokens, model.input_per_million)
            + token_cost(output_tokens, model.output_per_million))


def with_retry(base_cost: Decimal, retry_probability: Decimal) -> Decimal:
    if not D("0") <= retry_probability <= D("1"):
        raise ValueError("retry_probability must be between 0 and 1")
    return base_cost * (D("1") + retry_probability)


def keep_alive_times(return_minutes: Decimal, config: Config) -> list[Decimal]:
    """Scheduled refreshes strictly before return; each must occur before cache TTL expires."""
    if config.ttl_minutes <= 0 or config.keep_alive_interval_minutes <= 0:
        raise ValueError("TTL and keep-alive interval must be positive")
    if config.keep_alive_interval_minutes >= config.ttl_minutes:
        return []  # a refresh at/after expiration cannot preserve the cache
    points: list[Decimal] = []
    point = config.keep_alive_interval_minutes
    while point < return_minutes:
        points.append(point)
        point += config.keep_alive_interval_minutes
    return points


def cache_status_at(return_minutes: Decimal, config: Config) -> tuple[bool, list[Decimal]]:
    if return_minutes < 0:
        raise ValueError("return time cannot be negative")
    refreshes = keep_alive_times(return_minutes, config)
    last_activity = refreshes[-1] if refreshes else D("0")
    return return_minutes - last_activity <= config.ttl_minutes, refreshes


def keep_alive_cost(config: Config) -> Decimal:
    return request_cost(MODEL_A, cached_tokens=config.existing_context,
                        uncached_input_tokens=config.keep_alive_new_input,
                        output_tokens=config.keep_alive_output)


def warm_a_at(return_minutes: Decimal, config: Config) -> CostBreakdown:
    warm, refreshes = cache_status_at(return_minutes, config)
    maintenance = D(len(refreshes)) * keep_alive_cost(config)
    if warm:
        base = request_cost(MODEL_A, cached_tokens=config.existing_context,
                            uncached_input_tokens=config.new_input, output_tokens=config.expected_output)
        note = f"cache hit; {len(refreshes)} keep-alive refreshes before minute {return_minutes}"
    else:
        base = request_cost(MODEL_A, uncached_input_tokens=config.existing_context + config.new_input,
                            output_tokens=config.expected_output)
        note = "cache expired; prefix is charged as uncached input"
    req = with_retry(base, config.warm_retry_probability)
    return CostBreakdown("Warm A", MODEL_A.name, req, maintenance, req + maintenance, note)


def compact_at(config: Config) -> CostBreakdown:
    compaction = request_cost(MODEL_B, uncached_input_tokens=config.existing_context,
                              output_tokens=config.compaction_output)
    variants = []
    for model in (MODEL_A, MODEL_B):
        base = request_cost(model, uncached_input_tokens=config.compacted_context + config.new_input,
                            output_tokens=config.expected_output)
        variants.append((with_retry(base, config.compact_retry_probability), model))
    req, model = min(variants, key=lambda item: item[0])
    return CostBreakdown("Cold & Compact", model.name, req, compaction, req + compaction,
                         f"compaction via Model B; selected Compact -> {model.name}")


def switch_b_at(config: Config) -> CostBreakdown:
    base = request_cost(MODEL_B, uncached_input_tokens=config.existing_context + config.new_input,
                        output_tokens=config.expected_output)
    req = with_retry(base, config.switch_retry_probability)
    return CostBreakdown("Switch B", MODEL_B.name, req, D("0"), req,
                         "Model A cache is not transferable to Model B")


def route_at(return_minutes: Decimal, config: Config = Config()) -> tuple[CostBreakdown, list[CostBreakdown]]:
    costs = [warm_a_at(return_minutes, config), compact_at(config), switch_b_at(config)]
    return min(costs, key=lambda item: item.total_cost), costs


def expected_keep_alives(return_probability: Decimal, horizon: Decimal, config: Config) -> Decimal:
    """P(return) times survival at each scheduled time for uniform T in [0,horizon]."""
    if not D("0") <= return_probability <= D("1") or horizon <= 0:
        raise ValueError("probability must be 0..1 and horizon must be positive")
    return sum((return_probability * (D("1") - t / horizon)
                for t in keep_alive_times(horizon + D("0.0000001"), config)), D("0"))


def expected_route(return_probability: Decimal, horizon: Decimal, config: Config = Config()) -> tuple[CostBreakdown, list[CostBreakdown]]:
    # Request cost conditional on return is time-invariant for compact/switch.
    warm_request = request_cost(MODEL_A, cached_tokens=config.existing_context,
                                uncached_input_tokens=config.new_input, output_tokens=config.expected_output)
    warm_req = with_retry(warm_request, config.warm_retry_probability) * return_probability
    warm_maintenance = keep_alive_cost(config) * expected_keep_alives(return_probability, horizon, config)
    warm = CostBreakdown("Warm A", MODEL_A.name, warm_req, warm_maintenance, warm_req + warm_maintenance,
                         "expected: uniform return time conditional on a return")
    compact = compact_at(config)
    compact = CostBreakdown(compact.strategy, compact.model, compact.request_cost * return_probability,
                            compact.maintenance_or_compaction_cost * return_probability,
                            compact.total_cost * return_probability, compact.detail)
    switch = switch_b_at(config)
    switch = CostBreakdown(switch.strategy, switch.model, switch.request_cost * return_probability,
                           D("0"), switch.total_cost * return_probability, switch.detail)
    costs = [warm, compact, switch]
    return min(costs, key=lambda item: item.total_cost), costs


def sensitivity_segments(config: Config = Config(), horizon: Decimal = D("10"), steps: int = 100) -> list[tuple[Decimal, Decimal, str]]:
    winners: list[str] = []
    for i in range(steps + 1):
        winner, _ = expected_route(D(i) / D(steps), horizon, config)
        winners.append(winner.strategy)
    segments: list[tuple[Decimal, Decimal, str]] = []
    start = 0
    for i in range(1, len(winners) + 1):
        if i == len(winners) or winners[i] != winners[start]:
            segments.append((D(start) / D(steps), D(i - 1) / D(steps), winners[start]))
            start = i
    return segments


def money(value: Decimal) -> str:
    return f"${value.quantize(D('0.000001'))}"


def render(title: str, winner: CostBreakdown, costs: Iterable[CostBreakdown]) -> str:
    rows = list(costs)
    maximum = max((row.total_cost for row in rows), default=D("0"))
    out = [f"\n{title}", "Strategy           Model     Request     Maint/Compact   Total       Decision",
           "-" * 82]
    for row in rows:
        bar = "#" * (0 if maximum == 0 else max(1, int(row.total_cost / maximum * 20)))
        decision = "<- recommended" if row == winner else ""
        out.append(f"{row.strategy:<18} {row.model:<9} {money(row.request_cost):>10} {money(row.maintenance_or_compaction_cost):>14} {money(row.total_cost):>10}  {decision} {bar}")
    out.append(f"Recommendation: {winner.strategy} / {winner.model}, {money(winner.total_cost)}. {winner.detail}")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache-Aware Model Router simulation")
    sub = parser.add_subparsers(dest="command", required=True)
    at = sub.add_parser("at-time", help="simulate an exact return time")
    at.add_argument("--minutes", type=Decimal, required=True)
    prob = sub.add_parser("probability", help="simulate probability of return within horizon")
    prob.add_argument("--return-probability", type=Decimal, required=True)
    prob.add_argument("--horizon", type=Decimal, default=D("10"))
    sub.add_parser("demo", help="run the three required scenarios")
    sen = sub.add_parser("sensitivity", help="scan break-even return probability")
    sen.add_argument("--horizon", type=Decimal, default=D("10"))
    args = parser.parse_args()
    config = Config()
    if args.command == "at-time":
        winner, costs = route_at(args.minutes, config)
        print(render(f"Return after {args.minutes} minutes", winner, costs))
    elif args.command == "probability":
        winner, costs = expected_route(args.return_probability, args.horizon, config)
        print(render(f"P(return ≤ {args.horizon}m) = {args.return_probability}", winner, costs))
    elif args.command == "demo":
        for minutes in (D("3"), D("7")):
            winner, costs = route_at(minutes, config)
            print(render(f"Scenario: return after {minutes} minutes", winner, costs))
        winner, costs = expected_route(D("0.6"), D("10"), config)
        print(render("Scenario: 60% return within 10 minutes", winner, costs))
    else:
        segments = sensitivity_segments(config, args.horizon)
        print(f"Sensitivity: return probability 0-100%, horizon {args.horizon} minutes")
        if len(segments) == 1:
            print("No break-even point in the evaluated range")
        for low, high, strategy in segments:
            print(f"  P={low:.0%}-{high:.0%}: {strategy}")


if __name__ == "__main__":
    main()
