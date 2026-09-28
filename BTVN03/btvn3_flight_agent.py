#!/usr/bin/env python3
"""SE373 BTVN03 - Controlled flight-booking agents with deterministic mock tools.

The deterministic policy supports repeatable benchmarking without an API key.
``--model-mode langchain`` enables Gemini through LangChain for ReAct and
structured planning for Plan/Hybrid, with the same controlled mock harness.
"""

from __future__ import annotations

import argparse
import csv
import copy
import json
import os
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypedDict

from dotenv import load_dotenv
from pydantic import BaseModel, Field


# 1. CONFIG

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")
DEFAULT_DATE = "2026-10-07"
PATTERNS = ("react", "plan", "hybrid")
SCENARIOS = ("S1", "S2", "S3", "S4", "S5", "S6")
MAX_STEPS = 18
LOOP_THRESHOLD = 3
STALL_THRESHOLD = 5
TIMEOUT_RETRIES_PER_FLIGHT = 2


# 2. DATA MODELS

class TerminationReason(str, Enum):
    SUCCESS = "success"
    NEED_HUMAN = "need_human"
    LOOP = "loop"
    STALL = "stall"
    BUDGET_EXCEEDED = "budget_exceeded"
    FAILURE = "failure"


class BookingConstraints(BaseModel):
    origin: str
    destination: str
    depart_date: str
    latest_departure: str
    max_price: int
    seat_preference: str | None = None
    refundable_only: bool = False
    auto_pay_limit: int = 1_500_000


class Flight(BaseModel):
    flight_id: str
    origin: str
    destination: str
    depart_date: str
    departure_time: str
    price: int
    refundable: bool
    available_seats: list[str] = Field(default_factory=list)


class SeatAvailability(BaseModel):
    status: Literal["available", "full", "timeout", "not_found"]
    flight_id: str
    available_seats: list[str] = Field(default_factory=list)
    refundable: bool | None = None
    environment_changed: bool = False


class Booking(BaseModel):
    booking_code: str
    flight_id: str
    seat: str
    origin: str
    destination: str
    depart_date: str
    departure_time: str
    price: int
    refundable: bool
    status: Literal["held", "confirmed", "cancelled"]
    paid: bool = False


class PlanStep(BaseModel):
    id: int
    objective: str
    expected_tool: str | None = None
    argument_source: str | None = None


class AgentPlan(BaseModel):
    """Structured output returned by a LangChain planner."""

    steps: list[PlanStep] = Field(min_length=1, max_length=8)


class Handoff(BaseModel):
    status: str
    current_state: dict[str, Any]
    side_effects_done: list[str]
    attempts: list[str]
    blocker: str
    question_for_human: str


class RunMetrics(BaseModel):
    pattern: str
    scenario: str
    model_mode: str = "deterministic"
    scenario_class: Literal["autonomous", "need_human", "no_option", "unknown"] = "unknown"
    success: bool = False
    constraint_violations: int = 0
    permission_violations: int = 0
    permission_blocks: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    iterations: int = 0
    latency_ms: float = 0.0
    replans: int = 0
    loop_detected: bool = False
    stall_detected: bool = False
    termination_reason: str | None = None
    handoff_valid: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None


class Action(BaseModel):
    tool: Literal[
        "search_flights", "check_seat", "book_seat", "pay_booking", "get_booking"
    ]
    args: dict[str, Any] = Field(default_factory=dict)


class TraceEntry(BaseModel):
    iteration: int
    pattern: str
    action: str
    args: dict[str, Any]
    observation: dict[str, Any]
    progress: int
    permission: str
    completion: bool = False


class AgentState(TypedDict):
    """Shared logical state shape required by all three agent architectures."""

    goal: str
    constraints: BookingConstraints
    messages: list[dict[str, Any]]
    plan: list[PlanStep]
    current_step: int
    tool_history: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    booking_code: str | None
    iteration: int
    model_calls: int
    tool_calls: int
    termination_reason: str | None
    handoff: dict[str, Any] | None


@dataclass
class RuntimeState:
    goal: str
    constraints: BookingConstraints
    pattern: str
    scenario: str
    metrics: RunMetrics
    messages: list[dict[str, Any]] = field(default_factory=list)
    plan: list[PlanStep] = field(default_factory=list)
    plan_history: list[list[PlanStep]] = field(default_factory=list)
    current_step: int = 0
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    booking_code: str | None = None
    verified_booking_code: str | None = None
    selected_flight_id: str | None = None
    iteration: int = 0
    termination_reason: TerminationReason | None = None
    handoff: Handoff | None = None
    attempts: list[str] = field(default_factory=list)
    side_effects_done: list[str] = field(default_factory=list)
    no_progress_count: int = 0
    trace: list[TraceEntry] = field(default_factory=list)


# 3. MOCK DATABASE

class MockFlightDB:
    """Deterministic mock environment.  ``reset`` makes every run comparable."""

    def __init__(self) -> None:
        self._base_flights = [
            Flight(flight_id="VN122", origin="SGN", destination="DAD", depart_date=DEFAULT_DATE, departure_time="08:00", price=1_850_000, refundable=True, available_seats=["12A", "12B"]),
            Flight(flight_id="VJ604", origin="SGN", destination="DAD", depart_date=DEFAULT_DATE, departure_time="09:30", price=1_650_000, refundable=False, available_seats=[]),
            Flight(flight_id="QH118", origin="SGN", destination="DAD", depart_date=DEFAULT_DATE, departure_time="10:15", price=2_300_000, refundable=True, available_seats=["14A", "14B"]),
            Flight(flight_id="QH120", origin="SGN", destination="DAD", depart_date=DEFAULT_DATE, departure_time="11:30", price=1_950_000, refundable=True, available_seats=["16A", "16C"]),
            Flight(flight_id="VN134", origin="SGN", destination="DAD", depart_date=DEFAULT_DATE, departure_time="13:30", price=1_500_000, refundable=True, available_seats=["18A"]),
            Flight(flight_id="VN216", origin="SGN", destination="HAN", depart_date=DEFAULT_DATE, departure_time="08:45", price=1_700_000, refundable=True, available_seats=["10A"]),
            Flight(flight_id="VJ130", origin="DAD", destination="SGN", depart_date=DEFAULT_DATE, departure_time="10:00", price=1_600_000, refundable=False, available_seats=["20A"]),
            Flight(flight_id="QH201", origin="SGN", destination="DAD", depart_date="2026-10-08", departure_time="09:15", price=1_400_000, refundable=True, available_seats=["22A"]),
        ]
        self.reset("S1")

    def reset(self, scenario_id: str) -> None:
        if scenario_id not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario_id}")
        self.scenario_id = scenario_id
        self.flights: dict[str, Flight] = {
            flight.flight_id: flight.model_copy(deep=True) for flight in self._base_flights
        }
        self.bookings: dict[str, Booking] = {}
        self._booking_sequence = 0
        self._timeout_flights: set[str] = set()
        self._s6_change_fired = False

        if scenario_id == "S2":
            self.flights["VN122"].available_seats = []
        elif scenario_id == "S3":
            for flight in self.flights.values():
                if (
                    flight.origin == "SGN"
                    and flight.destination == "DAD"
                    and flight.depart_date == DEFAULT_DATE
                    and flight.departure_time <= "12:00"
                ):
                    flight.price = max(flight.price, 2_100_000)
        elif scenario_id == "S5":
            self._timeout_flights.add("VN122")

    def search_flights(self, origin: str, destination: str, depart_date: str) -> dict[str, Any]:
        flights = [
            flight.model_dump()
            for flight in self.flights.values()
            if flight.origin == origin
            and flight.destination == destination
            and flight.depart_date == depart_date
        ]
        flights.sort(key=lambda item: (item["departure_time"], item["price"]))
        return {"status": "ok", "flights": flights}

    def check_seat(self, flight_id: str) -> dict[str, Any]:
        flight = self.flights.get(flight_id)
        if not flight:
            return SeatAvailability(status="not_found", flight_id=flight_id).model_dump()
        if flight_id in self._timeout_flights:
            return SeatAvailability(status="timeout", flight_id=flight_id).model_dump()
        if self.scenario_id == "S6" and flight_id == "VN122" and not self._s6_change_fired:
            self._s6_change_fired = True
            flight.available_seats = []
            return SeatAvailability(
                status="full", flight_id=flight_id, refundable=flight.refundable, environment_changed=True
            ).model_dump()
        if not flight.available_seats:
            return SeatAvailability(status="full", flight_id=flight_id, refundable=flight.refundable).model_dump()
        return SeatAvailability(
            status="available",
            flight_id=flight_id,
            available_seats=flight.available_seats.copy(),
            refundable=flight.refundable,
        ).model_dump()

    def book_seat(self, flight_id: str, seat: str) -> dict[str, Any]:
        flight = self.flights.get(flight_id)
        if not flight:
            return {"status": "not_found", "flight_id": flight_id}
        if seat not in flight.available_seats:
            return {"status": "unavailable", "flight_id": flight_id, "seat": seat}
        flight.available_seats.remove(seat)
        self._booking_sequence += 1
        code = f"BOOK{self._booking_sequence:03d}"
        booking = Booking(
            booking_code=code,
            flight_id=flight.flight_id,
            seat=seat,
            origin=flight.origin,
            destination=flight.destination,
            depart_date=flight.depart_date,
            departure_time=flight.departure_time,
            price=flight.price,
            refundable=flight.refundable,
            status="held",
        )
        self.bookings[code] = booking
        return {"status": "held", "booking": booking.model_dump()}

    def pay_booking(self, booking_code: str) -> dict[str, Any]:
        booking = self.bookings.get(booking_code)
        if not booking:
            return {"status": "not_found", "booking_code": booking_code}
        if booking.status != "held":
            return {"status": "invalid_state", "booking": booking.model_dump()}
        booking.status = "confirmed"
        booking.paid = True
        return {"status": "confirmed", "booking": booking.model_dump()}

    def get_booking(self, booking_code: str) -> dict[str, Any]:
        booking = self.bookings.get(booking_code)
        if not booking:
            return {"status": "not_found", "booking_code": booking_code}
        return {"status": "ok", "booking": booking.model_dump()}

    def invoke(self, action: Action) -> dict[str, Any]:
        try:
            if action.tool == "search_flights":
                return self.search_flights(**action.args)
            if action.tool == "check_seat":
                return self.check_seat(**action.args)
            if action.tool == "book_seat":
                return self.book_seat(**action.args)
            if action.tool == "pay_booking":
                return self.pay_booking(**action.args)
            if action.tool == "get_booking":
                return self.get_booking(**action.args)
        except TypeError as error:
            return {"status": "invalid_arguments", "detail": str(error)}
        return {"status": "unknown_tool"}


# 4. MOCK TOOLS

def search_flights(db: MockFlightDB, origin: str, destination: str, depart_date: str) -> dict[str, Any]:
    """Read-only structured mock tool."""
    return db.search_flights(origin, destination, depart_date)


def check_seat(db: MockFlightDB, flight_id: str) -> dict[str, Any]:
    """Read-only structured mock tool; S5 intentionally returns timeouts."""
    return db.check_seat(flight_id)


def book_seat(db: MockFlightDB, flight_id: str, seat: str) -> dict[str, Any]:
    """Side-effectful mock tool that holds one seat."""
    return db.book_seat(flight_id, seat)


def pay_booking(db: MockFlightDB, booking_code: str) -> dict[str, Any]:
    """High-risk mock payment.  It never contacts a real payment service."""
    return db.pay_booking(booking_code)


def get_booking(db: MockFlightDB, booking_code: str) -> dict[str, Any]:
    """Read-only structured booking lookup."""
    return db.get_booking(booking_code)


# 5. HARNESS LAYERS

def _matching_flight(flight: Flight, constraints: BookingConstraints) -> bool:
    return (
        flight.origin == constraints.origin
        and flight.destination == constraints.destination
        and flight.depart_date == constraints.depart_date
        and flight.departure_time <= constraints.latest_departure
        and flight.price <= constraints.max_price
        and (not constraints.refundable_only or flight.refundable)
    )


class ConstraintHarness:
    def validate_action(
        self,
        action: Action,
        db: MockFlightDB,
        constraints: BookingConstraints,
        observations: list[dict[str, Any]],
        active_booking_code: str | None,
    ) -> tuple[bool, str]:
        if action.tool == "search_flights":
            exact_route = (
                action.args.get("origin") == constraints.origin
                and action.args.get("destination") == constraints.destination
                and action.args.get("depart_date") == constraints.depart_date
            )
            return (exact_route, "Search arguments must equal structured BookingConstraints")
        if action.tool == "book_seat":
            if active_booking_code:
                return False, "Only one active seat hold is allowed per run"
            flight = db.flights.get(str(action.args.get("flight_id", "")))
            if flight is None or not _matching_flight(flight, constraints):
                return False, "Cannot hold a flight outside route/date/time/price/refund constraints"
            seat = str(action.args.get("seat", ""))
            observed = any(
                item["tool"] == "check_seat"
                and item["result"].get("flight_id") == flight.flight_id
                and item["result"].get("status") == "available"
                and seat in item["result"].get("available_seats", [])
                for item in observations
            )
            return observed, "Seat must first be observed available through check_seat"
        if action.tool == "pay_booking":
            booking = db.bookings.get(str(action.args.get("booking_code", "")))
            if not booking:
                return False, "Cannot pay an unknown booking"
            flight = db.flights.get(booking.flight_id)
            return (
                flight is not None and _matching_flight(flight, constraints),
                "Cannot pay a booking that violates BookingConstraints",
            )
        return True, ""

    def validate_result(self, action: Action, result: dict[str, Any], constraints: BookingConstraints) -> tuple[bool, str]:
        if action.tool in {"book_seat", "pay_booking", "get_booking"} and "booking" in result:
            booking = Booking.model_validate(result["booking"])
            valid = (
                booking.origin == constraints.origin
                and booking.destination == constraints.destination
                and booking.depart_date == constraints.depart_date
                and booking.departure_time <= constraints.latest_departure
                and booking.price <= constraints.max_price
                and (not constraints.refundable_only or booking.refundable)
            )
            return valid, "Tool returned a booking that violates BookingConstraints"
        return True, ""


class CompletionHarness:
    """Completion is code-verified from DB state, never inferred from model text."""

    def is_complete(self, state: RuntimeState, db: MockFlightDB) -> bool:
        if not state.booking_code or state.verified_booking_code != state.booking_code:
            return False
        booking = db.bookings.get(state.booking_code)
        if not booking:
            return False
        constraints = state.constraints
        return (
            booking.status == "confirmed"
            and booking.paid
            and booking.origin == constraints.origin
            and booking.destination == constraints.destination
            and booking.depart_date == constraints.depart_date
            and booking.departure_time <= constraints.latest_departure
            and booking.price <= constraints.max_price
            and (not constraints.refundable_only or booking.refundable)
        )


class PermissionHarness:
    def __init__(self, human_payment_approval: bool = False) -> None:
        self.human_payment_approval = human_payment_approval

    def check(self, action: Action, db: MockFlightDB, constraints: BookingConstraints) -> tuple[str, str]:
        if action.tool != "pay_booking":
            return "ALLOW", ""
        booking = db.bookings.get(str(action.args.get("booking_code", "")))
        if not booking:
            return "BLOCK", "Unknown booking cannot be paid"
        needs_approval = booking.price > constraints.auto_pay_limit or not booking.refundable
        if needs_approval and not self.human_payment_approval:
            reason = "payment exceeds automatic payment limit" if booking.price > constraints.auto_pay_limit else "ticket is non-refundable"
            return "NEED_APPROVAL", reason
        return "ALLOW", ""


class HandoffHarness:
    def create(self, state: RuntimeState, blocker: str, status: str = "waiting_for_approval") -> Handoff:
        current: dict[str, Any] = {"scenario": state.scenario}
        if state.selected_flight_id:
            current["flight"] = state.selected_flight_id
        if state.booking_code:
            current["booking_code"] = state.booking_code
        booking_data: dict[str, Any] | None = None
        for observation in reversed(state.observations):
            possible_booking = observation["result"].get("booking")
            if possible_booking:
                booking_data = possible_booking
                break
        if booking_data:
            current.update(
                {
                    "flight": booking_data["flight_id"],
                    "seat": booking_data["seat"],
                    "price": booking_data["price"],
                    "refundable": booking_data["refundable"],
                }
            )
        if state.observations:
            current["last_observation"] = state.observations[-1]
        question = "No human action is required."
        if status == "waiting_for_approval" and state.booking_code:
            amount = f"{booking_data['price']:,}" if booking_data else "the requested"
            flight_id = booking_data["flight_id"] if booking_data else state.selected_flight_id or "selected flight"
            question = f"Approve payment of {amount} VND for {flight_id}?"
        return Handoff(
            status=status,
            current_state=current,
            side_effects_done=state.side_effects_done.copy(),
            attempts=state.attempts[-8:],
            blocker=blocker,
            question_for_human=question,
        )


class LoopDetector:
    def __init__(self, threshold: int = LOOP_THRESHOLD) -> None:
        self.threshold = threshold
        self._actions: Counter[str] = Counter()

    def record(self, action: Action) -> bool:
        signature = f"{action.tool}:{json.dumps(action.args, sort_keys=True)}"
        self._actions[signature] += 1
        return self._actions[signature] >= self.threshold


class BudgetGuard:
    def __init__(self, max_steps: int = MAX_STEPS) -> None:
        self.max_steps = max_steps

    def exhausted(self, state: RuntimeState) -> bool:
        return state.metrics.iterations >= self.max_steps or state.metrics.model_calls >= self.max_steps


class TraceLogger:
    def add(self, state: RuntimeState, action: Action, result: dict[str, Any], permission: str, completion: bool) -> None:
        state.trace.append(
            TraceEntry(
                iteration=state.metrics.iterations,
                pattern=state.pattern,
                action=action.tool,
                args=copy.deepcopy(action.args),
                observation=copy.deepcopy(result),
                progress=len(state.side_effects_done),
                permission=permission,
                completion=completion,
            )
        )


class ExecutionHarness:
    """The only component permitted to invoke mock tools during an agent run."""

    def __init__(self, db: MockFlightDB, state: RuntimeState, human_payment_approval: bool = False) -> None:
        self.db = db
        self.state = state
        self.constraints = ConstraintHarness()
        self.completion = CompletionHarness()
        self.permissions = PermissionHarness(human_payment_approval)
        self.handoff = HandoffHarness()
        self.loop = LoopDetector()
        self.budget = BudgetGuard()
        self.logger = TraceLogger()
        self._lock = threading.RLock()

    def _terminate(self, reason: TerminationReason, blocker: str = "") -> None:
        self.state.termination_reason = reason
        self.state.metrics.termination_reason = reason.value
        if reason == TerminationReason.NEED_HUMAN:
            self.state.handoff = self.handoff.create(self.state, blocker)
        elif reason != TerminationReason.SUCCESS:
            self.state.handoff = self.handoff.create(self.state, blocker or reason.value, status="stopped")
        if self.state.handoff:
            self.state.metrics.handoff_valid = bool(Handoff.model_validate(self.state.handoff.model_dump()))

    def _record_result(self, action: Action, result: dict[str, Any]) -> None:
        self.state.tool_history.append({"tool": action.tool, "args": copy.deepcopy(action.args)})
        self.state.observations.append({"tool": action.tool, "result": copy.deepcopy(result)})
        status = str(result.get("status", "unknown"))
        self.state.attempts.append(f"{action.tool}: {status}")
        if action.tool == "check_seat" and status == "available":
            self.state.selected_flight_id = str(result["flight_id"])
            self.state.no_progress_count = 0
        elif action.tool == "book_seat" and status == "held":
            booking = Booking.model_validate(result["booking"])
            self.state.booking_code = booking.booking_code
            self.state.selected_flight_id = booking.flight_id
            self.state.side_effects_done.append(f"seat {booking.seat} held for {booking.flight_id}")
            self.state.no_progress_count = 0
        elif action.tool == "pay_booking" and status == "confirmed":
            self.state.side_effects_done.append(f"mock payment confirmed for {self.state.booking_code}")
            self.state.no_progress_count = 0
        elif action.tool == "get_booking" and status == "ok":
            booking = Booking.model_validate(result["booking"])
            if booking.status == "confirmed" and booking.paid:
                self.state.verified_booking_code = booking.booking_code
            self.state.no_progress_count = 0
        elif status in {"timeout", "invalid_arguments", "not_found", "unavailable"}:
            self.state.no_progress_count += 1
        else:
            # A full seat check is useful information: it advances candidate selection.
            self.state.no_progress_count = 0

    def execute(self, action: Action) -> dict[str, Any]:
        # LangChain may dispatch multiple tool calls from one model message.
        with self._lock:
            return self._execute_locked(action)

    def _execute_locked(self, action: Action) -> dict[str, Any]:
        if self.state.termination_reason:
            return {"status": "terminated", "reason": self.state.termination_reason.value}
        self.state.metrics.iterations += 1
        self.state.iteration = self.state.metrics.iterations

        valid, message = self.constraints.validate_action(
            action, self.db, self.state.constraints, self.state.observations, self.state.booking_code
        )
        if not valid:
            self.state.metrics.constraint_violations += 1
            result = {"status": "constraint_rejected", "detail": message}
            self._record_result(action, result)
            self.logger.add(self.state, action, result, "BLOCK", False)
            self._terminate(TerminationReason.FAILURE, message)
            return result

        permission, message = self.permissions.check(action, self.db, self.state.constraints)
        if permission != "ALLOW":
            if permission == "NEED_APPROVAL":
                self.state.metrics.permission_blocks += 1
                result = {"status": "need_human", "detail": message}
                self._record_result(action, result)
                self.logger.add(self.state, action, result, permission, False)
                self._terminate(TerminationReason.NEED_HUMAN, message)
                return result
            self.state.metrics.permission_blocks += 1
            result = {"status": "permission_blocked", "detail": message}
            self._record_result(action, result)
            self.logger.add(self.state, action, result, permission, False)
            self._terminate(TerminationReason.FAILURE, message)
            return result

        result = self.db.invoke(action)
        self.state.metrics.tool_calls += 1
        self._record_result(action, result)
        valid_result, result_message = self.constraints.validate_result(action, result, self.state.constraints)
        if not valid_result:
            self.state.metrics.constraint_violations += 1
            self.logger.add(self.state, action, result, permission, False)
            self._terminate(TerminationReason.FAILURE, result_message)
            return result

        complete = self.completion.is_complete(self.state, self.db)
        self.logger.add(self.state, action, result, permission, complete)
        # Required post-observation order: completion -> loop -> stall -> budget.
        if complete:
            self.state.metrics.success = True
            self._terminate(TerminationReason.SUCCESS)
        elif self.loop.record(action):
            self.state.metrics.loop_detected = True
            self._terminate(TerminationReason.LOOP, "Repeated identical tool call detected")
        elif self.state.no_progress_count >= STALL_THRESHOLD:
            self.state.metrics.stall_detected = True
            self._terminate(TerminationReason.STALL, "No observable progress")
        elif self.budget.exhausted(self.state):
            self._terminate(TerminationReason.BUDGET_EXCEEDED, "Step or model-call budget exhausted")
        return result


# 6. REACT AGENT

def _last_result(state: RuntimeState, tool: str, flight_id: str | None = None) -> dict[str, Any] | None:
    for observation in reversed(state.observations):
        if observation["tool"] != tool:
            continue
        result = observation["result"]
        if flight_id is None or result.get("flight_id") == flight_id:
            return result
    return None


def _candidate_flights(state: RuntimeState) -> list[Flight]:
    search = _last_result(state, "search_flights")
    if not search:
        return []
    flights = [Flight.model_validate(item) for item in search.get("flights", [])]
    return sorted(
        [flight for flight in flights if _matching_flight(flight, state.constraints)],
        key=lambda flight: (flight.departure_time, flight.price),
    )


def _next_candidate(state: RuntimeState) -> Flight | None:
    """Retry a transient timeout twice, then try another observed candidate."""
    for flight in _candidate_flights(state):
        check = _last_result(state, "check_seat", flight.flight_id)
        if not check or check.get("status") == "available":
            return flight
        if check.get("status") == "timeout":
            timeouts = sum(
                observation["tool"] == "check_seat"
                and observation["result"].get("flight_id") == flight.flight_id
                and observation["result"].get("status") == "timeout"
                for observation in state.observations
            )
            if timeouts < TIMEOUT_RETRIES_PER_FLIGHT:
                return flight
    return None


def _preferred_seat(availability: dict[str, Any], preference: str | None) -> str | None:
    seats = list(availability.get("available_seats", []))
    if preference == "window":
        return next((seat for seat in seats if seat.endswith("A") or seat.endswith("F")), None) or (seats[0] if seats else None)
    return seats[0] if seats else None


class DeterministicReActPolicy:
    """A transparent stand-in for an LLM; it uses only observations as facts."""

    def propose(self, state: RuntimeState) -> Action | None:
        if not _last_result(state, "search_flights"):
            c = state.constraints
            return Action(tool="search_flights", args={"origin": c.origin, "destination": c.destination, "depart_date": c.depart_date})
        if state.booking_code:
            payment = _last_result(state, "pay_booking")
            if not payment:
                return Action(tool="pay_booking", args={"booking_code": state.booking_code})
            if payment.get("status") == "confirmed" and not _last_result(state, "get_booking"):
                return Action(tool="get_booking", args={"booking_code": state.booking_code})
            return None
        candidate = _next_candidate(state)
        if not candidate:
            return None
        availability = _last_result(state, "check_seat", candidate.flight_id)
        if not availability or availability.get("status") == "timeout":
            return Action(tool="check_seat", args={"flight_id": candidate.flight_id})
        if availability.get("status") == "available":
            seat = _preferred_seat(availability, state.constraints.seat_preference)
            if seat:
                return Action(tool="book_seat", args={"flight_id": candidate.flight_id, "seat": seat})
        return None


def _record_model_call(state: RuntimeState, action: Action) -> None:
    state.metrics.model_calls += 1
    state.messages.append({"role": "model", "tool": action.tool, "args": copy.deepcopy(action.args)})


def run_react(state: RuntimeState, harness: ExecutionHarness) -> None:
    policy = DeterministicReActPolicy()
    while not state.termination_reason:
        action = policy.propose(state)
        if not action:
            harness._terminate(TerminationReason.FAILURE, "No remaining feasible action from observed data")
            break
        _record_model_call(state, action)
        harness.execute(action)


def run_langchain_react(state: RuntimeState, harness: ExecutionHarness) -> None:
    """LangChain create_agent with Gemini; tool functions are harness wrappers."""
    try:
        from langchain.agents import create_agent
        from langchain_core.callbacks import BaseCallbackHandler
        from langchain_core.tools import tool
    except ImportError as error:
        raise RuntimeError("Install requirements.txt before using --model-mode langchain") from error

    def call(action: Action) -> str:
        result = harness.execute(action)
        return json.dumps(result, ensure_ascii=False)

    @tool("search_flights")
    def lc_search_flights(origin: str, destination: str, depart_date: str) -> str:
        """Search flights. Use for all flight facts."""
        return call(Action(tool="search_flights", args={"origin": origin, "destination": destination, "depart_date": depart_date}))

    @tool("check_seat")
    def lc_check_seat(flight_id: str) -> str:
        """Check seat availability for a flight ID returned by search."""
        return call(Action(tool="check_seat", args={"flight_id": flight_id}))

    @tool("book_seat")
    def lc_book_seat(flight_id: str, seat: str) -> str:
        """Hold an observed available seat; this is a side effect controlled by the harness."""
        return call(Action(tool="book_seat", args={"flight_id": flight_id, "seat": seat}))

    @tool("pay_booking")
    def lc_pay_booking(booking_code: str) -> str:
        """Pay an observed held booking; harness permission is enforced before execution."""
        return call(Action(tool="pay_booking", args={"booking_code": booking_code}))

    @tool("get_booking")
    def lc_get_booking(booking_code: str) -> str:
        """Verify the final booking state after payment."""
        return call(Action(tool="get_booking", args={"booking_code": booking_code}))

    system_prompt = (
        "You are a flight-booking agent. Use tools for all factual information. "
        "Never fabricate flight, seat, price, booking code, or booking status. "
        "Constraints are structured data. Do not bypass harness decisions. "
        "Stop after a tool reports need_human or terminated."
    )

    class ModelMetricsCallback(BaseCallbackHandler):
        def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, **kwargs: Any) -> None:
            state.metrics.model_calls += 1

        def on_llm_end(self, response: Any, **kwargs: Any) -> None:
            for generation_group in response.generations:
                for generation in generation_group:
                    usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
                    if usage:
                        state.metrics.input_tokens = (state.metrics.input_tokens or 0) + int(usage.get("input_tokens", 0))
                        state.metrics.output_tokens = (state.metrics.output_tokens or 0) + int(usage.get("output_tokens", 0))

    agent = create_agent(
        model=build_gemini_model(),
        tools=[lc_search_flights, lc_check_seat, lc_book_seat, lc_pay_booking, lc_get_booking],
        system_prompt=system_prompt,
    )
    try:
        response = agent.invoke(
            {"messages": [{"role": "user", "content": state.constraints.model_dump_json()}]},
            config={"recursion_limit": MAX_STEPS * 3, "callbacks": [ModelMetricsCallback()]},
        )
    except Exception as error:
        # The mock harness remains authoritative even if the provider fails.
        if not state.termination_reason:
            detail = str(error).replace(os.environ.get("GOOGLE_API_KEY", "\x00"), "[redacted]")[:240]
            harness._terminate(TerminationReason.FAILURE, f"LangChain/provider error: {type(error).__name__}: {detail}")
        return
    messages = response.get("messages", []) if isinstance(response, dict) else []
    state.metrics.model_calls = max(
        state.metrics.model_calls,
        sum(1 for message in messages if getattr(message, "type", "") == "ai"),
    )
    token_totals = [getattr(message, "usage_metadata", None) for message in messages]
    token_totals = [usage for usage in token_totals if usage]
    if token_totals and state.metrics.input_tokens is None:
        state.metrics.input_tokens = sum(int(usage.get("input_tokens", 0)) for usage in token_totals)
        state.metrics.output_tokens = sum(int(usage.get("output_tokens", 0)) for usage in token_totals)
    if not state.termination_reason:
        harness._terminate(TerminationReason.FAILURE, "LangChain agent stopped without code-verified completion")


def build_gemini_model() -> Any:
    """The only model factory; never embeds or logs the Google AI Studio key."""
    model_name = os.environ.get("SE373_MODEL", "").strip()
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not model_name or not api_key:
        raise RuntimeError("Set SE373_MODEL and GOOGLE_API_KEY in BTVN03/.env for --model-mode langchain")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as error:
        raise RuntimeError("Install BTVN03/requirements.txt to use Google AI Studio") from error
    return ChatGoogleGenerativeAI(
        model=model_name,
        api_key=api_key,
        vertexai=False,
        request_timeout=30,
        retries=0,
    )


# 7. PLAN-THEN-EXECUTE AGENT

def initial_plan() -> list[PlanStep]:
    return [
        PlanStep(id=1, objective="Find matching flights", expected_tool="search_flights", argument_source="constraints"),
        PlanStep(id=2, objective="Check the first eligible candidate", expected_tool="check_seat", argument_source="next_candidate"),
        PlanStep(id=3, objective="Hold the observed preferred seat", expected_tool="book_seat", argument_source="available_check"),
        PlanStep(id=4, objective="Pay the held booking", expected_tool="pay_booking", argument_source="booking_code"),
        PlanStep(id=5, objective="Verify confirmed booking", expected_tool="get_booking", argument_source="booking_code"),
    ]


def resolve_plan_step(state: RuntimeState, step: PlanStep) -> Action | None:
    if step.expected_tool == "search_flights":
        c = state.constraints
        return Action(tool="search_flights", args={"origin": c.origin, "destination": c.destination, "depart_date": c.depart_date})
    if step.expected_tool == "check_seat":
        flight = _next_candidate(state)
        return Action(tool="check_seat", args={"flight_id": flight.flight_id}) if flight else None
    if step.expected_tool == "book_seat":
        if not state.selected_flight_id:
            return None
        availability = _last_result(state, "check_seat", state.selected_flight_id)
        seat = _preferred_seat(availability or {}, state.constraints.seat_preference)
        return Action(tool="book_seat", args={"flight_id": state.selected_flight_id, "seat": seat}) if seat else None
    if step.expected_tool == "pay_booking" and state.booking_code:
        return Action(tool="pay_booking", args={"booking_code": state.booking_code})
    if step.expected_tool == "get_booking" and state.booking_code:
        return Action(tool="get_booking", args={"booking_code": state.booking_code})
    return None


def run_plan_then_execute(state: RuntimeState, harness: ExecutionHarness, model: Any = None) -> None:
    # One planner call, then the LangGraph executor runs the immutable plan.
    run_langgraph_plan(state, harness, model=model, hybrid=False)


# 8. HYBRID AGENT

def hybrid_plan(state: RuntimeState) -> list[PlanStep]:
    if not _last_result(state, "search_flights"):
        return initial_plan()
    return [
        PlanStep(id=1, objective="Check next eligible candidate after observation", expected_tool="check_seat", argument_source="next_candidate"),
        PlanStep(id=2, objective="Hold observed preferred seat", expected_tool="book_seat", argument_source="available_check"),
        PlanStep(id=3, objective="Pay held booking", expected_tool="pay_booking", argument_source="booking_code"),
        PlanStep(id=4, objective="Verify confirmed booking", expected_tool="get_booking", argument_source="booking_code"),
    ]


def _needs_replan(action: Action, result: dict[str, Any]) -> bool:
    return action.tool == "check_seat" and (
        result.get("status") in {"full", "timeout"} or bool(result.get("environment_changed"))
    )


def run_hybrid(state: RuntimeState, harness: ExecutionHarness, k: int = 2, *, model: Any = None) -> None:
    run_langgraph_plan(state, harness, model=model, hybrid=True, k=k)


class WorkflowGraphState(TypedDict):
    """Control state for LangGraph; domain state remains in RuntimeState."""

    cursor: int
    replan: bool


def _model_plan(state: RuntimeState, model: Any, *, replan: bool) -> list[PlanStep]:
    """Gemini chooses ordered tool objectives; the executor resolves only observed facts."""
    if model is None:
        return hybrid_plan(state) if replan else initial_plan()
    recent = state.observations[-6:]
    prompt = (
        "Create a concise ordered plan for booking a flight. Return structured AgentPlan. "
        "Allowed expected_tool values: search_flights, check_seat, book_seat, "
        "pay_booking, get_booking. The final goal requires get_booking. "
        "Never invent flight IDs, seats, prices, or booking codes. "
        "The executor resolves tool arguments from verified observations; use "
        "argument_source values constraints, next_candidate, available_check, booking_code. "
        "If search has not happened, start with search_flights. After a full or "
        "changed flight, check another candidate. After repeated timeouts, also "
        "check another candidate. Do not plan approval bypasses.\n"
        f"Constraints: {state.constraints.model_dump_json()}\n"
        f"Current booking code: {state.booking_code or 'none'}\n"
        f"Recent observations: {json.dumps(recent, ensure_ascii=False)}"
    )
    response = model.with_structured_output(AgentPlan).invoke(prompt)
    plan = AgentPlan.model_validate(response).steps
    allowed = {"search_flights", "check_seat", "book_seat", "pay_booking", "get_booking"}
    if any(step.expected_tool not in allowed for step in plan):
        raise ValueError("Planner emitted a tool outside the five mock tools")
    if not state.observations and plan[0].expected_tool != "search_flights":
        raise ValueError("Planner must search before using flight facts")
    return plan


def run_langgraph_plan(
    state: RuntimeState,
    harness: ExecutionHarness,
    *,
    model: Any,
    hybrid: bool,
    k: int = 2,
) -> None:
    """StateGraph for one-shot Plan or conditional Hybrid replanning."""
    from langgraph.graph import END, START, StateGraph

    if hybrid and k < 1:
        raise ValueError("Hybrid execution window k must be at least 1")

    def planner(graph_state: WorkflowGraphState) -> WorkflowGraphState:
        if state.metrics.model_calls >= MAX_STEPS:
            harness._terminate(TerminationReason.BUDGET_EXCEEDED, "Planner call budget exhausted")
            return {"cursor": 0, "replan": False}
        state.metrics.model_calls += 1
        try:
            state.plan = _model_plan(state, model, replan=bool(state.plan))
        except Exception as error:
            detail = str(error).replace(os.environ.get("GOOGLE_API_KEY", "\x00"), "[redacted]")[:240]
            harness._terminate(TerminationReason.FAILURE, f"Planner error: {type(error).__name__}: {detail}")
            return {"cursor": 0, "replan": False}
        state.plan_history.append(state.plan.copy())
        return {"cursor": 0, "replan": False}

    def executor(graph_state: WorkflowGraphState) -> WorkflowGraphState:
        cursor = graph_state["cursor"]
        steps_to_run = k if hybrid else len(state.plan)
        executed = 0
        while cursor < len(state.plan) and executed < steps_to_run and not state.termination_reason:
            step = state.plan[cursor]
            state.current_step = step.id
            action = resolve_plan_step(state, step)
            if action is None:
                if hybrid and _next_candidate(state):
                    return {"cursor": cursor, "replan": True}
                harness._terminate(TerminationReason.FAILURE, f"Plan step {step.id} lacks observed arguments")
                break
            result = harness.execute(action)
            cursor += 1
            executed += 1
            if _needs_replan(action, result):
                if hybrid and not state.termination_reason:
                    return {"cursor": cursor, "replan": True}
                if not state.termination_reason:
                    harness._terminate(TerminationReason.FAILURE, "One-shot plan became stale")
                break
        if cursor >= len(state.plan) and not state.termination_reason:
            harness._terminate(TerminationReason.FAILURE, "Plan ended without code-verified completion")
        return {"cursor": cursor, "replan": False}

    def route(graph_state: WorkflowGraphState) -> str:
        if state.termination_reason:
            return "end"
        if graph_state["replan"]:
            state.metrics.replans += 1
            return "planner"
        return "executor"

    graph = StateGraph(WorkflowGraphState)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_conditional_edges("executor", route, {"planner": "planner", "executor": "executor", "end": END})
    graph.compile().invoke({"cursor": 0, "replan": False}, config={"recursion_limit": MAX_STEPS * 3})


# 9. EVALUATION

def constraints_for(scenario: str) -> BookingConstraints:
    return BookingConstraints(
        origin="SGN",
        destination="DAD",
        depart_date=DEFAULT_DATE,
        latest_departure="12:00",
        max_price=2_000_000,
        seat_preference="window",
        refundable_only=False,
        auto_pay_limit=1_500_000 if scenario == "S4" else 2_000_000,
    )


def classify_scenario(
    db: MockFlightDB, constraints: BookingConstraints
) -> Literal["autonomous", "need_human", "no_option"]:
    """Independent oracle: probe a DB copy without changing the agent's run."""
    probe = copy.deepcopy(db)
    approval_option = False
    for flight in probe.flights.values():
        if not _matching_flight(flight, constraints):
            continue
        availability = probe.check_seat(flight.flight_id)
        if availability.get("status") != "available":
            continue
        if not _preferred_seat(availability, constraints.seat_preference):
            continue
        if flight.price <= constraints.auto_pay_limit and flight.refundable:
            return "autonomous"
        approval_option = True
    return "need_human" if approval_option else "no_option"


def audit_permission_violations(
    db: MockFlightDB, constraints: BookingConstraints, human_payment_approval: bool
) -> int:
    """Count committed payments that required approval but never received it."""
    if human_payment_approval:
        return 0
    return sum(
        booking.paid and (booking.price > constraints.auto_pay_limit or not booking.refundable)
        for booking in db.bookings.values()
    )


def new_state(pattern: str, scenario: str) -> RuntimeState:
    return RuntimeState(
        goal="Book a compliant SGN to DAD flight",
        constraints=constraints_for(scenario),
        pattern=pattern,
        scenario=scenario,
        metrics=RunMetrics(pattern=pattern, scenario=scenario),
    )


def run_pattern(
    pattern: str,
    scenario: str,
    *,
    human_payment_approval: bool = False,
    model_mode: str = "deterministic",
) -> RuntimeState:
    if pattern not in PATTERNS:
        raise ValueError(f"Unknown pattern: {pattern}")
    if model_mode not in {"deterministic", "langchain"}:
        raise ValueError(f"Unknown model mode: {model_mode}")
    db = MockFlightDB()
    db.reset(scenario)
    state = new_state(pattern, scenario)
    state.metrics.model_mode = model_mode
    state.metrics.scenario_class = classify_scenario(db, state.constraints)
    harness = ExecutionHarness(db, state, human_payment_approval)
    started = time.perf_counter()
    model = build_gemini_model() if model_mode == "langchain" and pattern != "react" else None
    if pattern == "react":
        if model_mode == "langchain":
            run_langchain_react(state, harness)
        else:
            run_react(state, harness)
    elif pattern == "plan":
        run_plan_then_execute(state, harness, model=model)
    else:
        run_hybrid(state, harness, model=model)
    state.metrics.latency_ms = round((time.perf_counter() - started) * 1_000, 3)
    state.metrics.permission_violations += audit_permission_violations(
        db, state.constraints, human_payment_approval
    )
    state.metrics.success = state.termination_reason == TerminationReason.SUCCESS
    state.metrics.termination_reason = state.termination_reason.value if state.termination_reason else None
    return state


def write_benchmark(rows: list[RunMetrics], output: Path | None = None) -> Path:
    output = output or PROJECT_DIR / "results.csv"
    fields = list(RunMetrics.model_fields)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["repeat", *fields])
        writer.writeheader()
        for index, metrics in enumerate(rows):
            record = metrics.model_dump()
            record["repeat"] = index // (len(PATTERNS) * len(SCENARIOS)) + 1
            writer.writerow(record)
    return output


def benchmark(repeats: int, model_mode: str = "deterministic", output: Path | None = None) -> list[RunMetrics]:
    rows: list[RunMetrics] = []
    for _ in range(repeats):
        for pattern in PATTERNS:
            for scenario in SCENARIOS:
                rows.append(run_pattern(pattern, scenario, model_mode=model_mode).metrics)
    write_benchmark(rows, output or PROJECT_DIR / ("results_gemini.csv" if model_mode == "langchain" else "results.csv"))
    return rows


def print_benchmark_summary(rows: list[RunMetrics], output: Path | None = None) -> None:
    output = output or PROJECT_DIR / "results.csv"
    print("\n================ BENCHMARK ================")
    print(f"{'Pattern':<10} {'Success':<9} {'Tools':<8} {'Steps':<8} {'Replans':<9} {'Violations':<11}")
    print("-" * 64)
    for pattern in PATTERNS:
        subset = [row for row in rows if row.pattern == pattern]
        success = sum(row.success for row in subset)
        tools = sum(row.tool_calls for row in subset) / len(subset)
        steps = sum(row.iterations for row in subset) / len(subset)
        replans = sum(row.replans for row in subset) / len(subset)
        violations = sum(row.constraint_violations + row.permission_violations for row in subset)
        print(f"{pattern:<10} {success}/{len(subset):<7} {tools:<8.2f} {steps:<8.2f} {replans:<9.2f} {violations:<11}")
    print(f"CSV: {output}")


def self_test() -> None:
    # Constraint rejection before side effect.
    db = MockFlightDB()
    db.reset("S1")
    state = new_state("react", "S1")
    harness = ExecutionHarness(db, state)
    rejected = harness.execute(Action(tool="book_seat", args={"flight_id": "VN134", "seat": "18A"}))
    assert rejected["status"] == "constraint_rejected" and not db.bookings

    # Completion is independently verified only after get_booking.
    completed = run_pattern("react", "S1")
    assert completed.termination_reason == TerminationReason.SUCCESS
    assert completed.metrics.success and completed.verified_booking_code

    # Permission blocks payment before the mock payment tool mutates state.
    approval = run_pattern("react", "S4")
    assert approval.termination_reason == TerminationReason.NEED_HUMAN
    assert approval.handoff and approval.handoff.status == "waiting_for_approval"
    assert approval.metrics.permission_blocks == 1 and approval.metrics.permission_violations == 0
    assert approval.handoff.current_state["seat"] == "12A"
    assert approval.handoff.current_state["price"] == 1_850_000
    assert not any("payment confirmed" in effect for effect in approval.side_effects_done)

    # S5 remains solvable: bounded retries switch from VN122 to QH120.
    recovered = run_pattern("react", "S5")
    assert recovered.termination_reason == TerminationReason.SUCCESS
    assert recovered.selected_flight_id == "QH120"
    assert recovered.metrics.scenario_class == "autonomous"

    # The loop guard itself still stops a repeated identical action.
    loop = LoopDetector()
    repeated = Action(tool="check_seat", args={"flight_id": "VN122"})
    assert not loop.record(repeated) and not loop.record(repeated) and loop.record(repeated)

    # S6 demonstrates the intended Plan-versus-Hybrid difference.
    stale_plan = run_pattern("plan", "S6")
    adaptive_hybrid = run_pattern("hybrid", "S6")
    assert stale_plan.termination_reason == TerminationReason.FAILURE
    assert adaptive_hybrid.termination_reason == TerminationReason.SUCCESS and adaptive_hybrid.metrics.replans > 0

    # Handoff schema has deterministic validation.
    Handoff.model_validate(approval.handoff.model_dump())
    print("Self-tests passed: constraint, completion, permission, timeout fallback, loop, handoff, plan-vs-hybrid.")


def render_trace(state: RuntimeState) -> None:
    actor = "MODEL" if state.metrics.model_mode == "langchain" else "SIMULATED_POLICY"
    for entry in state.trace:
        args = json.dumps(entry.args, ensure_ascii=False)
        observation = json.dumps(entry.observation, ensure_ascii=False)
        print(f"[{entry.iteration:02d}] {actor} -> {entry.action}({args})")
        print(f"[{entry.iteration:02d}] {entry.permission:<10} -> {observation}")
    print(f"\nSTOP -> {state.metrics.termination_reason}")
    print(json.dumps(state.metrics.model_dump(), ensure_ascii=False, indent=2))
    if state.handoff:
        print("HANDOFF ->")
        print(state.handoff.model_dump_json(indent=2))


# 10. CLI / MAIN

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SE373 BTVN03 controlled flight-agent benchmark")
    parser.add_argument("--pattern", choices=PATTERNS, help="Agent architecture to run")
    parser.add_argument("--scenario", choices=SCENARIOS, default="S1", help="Mock environment scenario")
    parser.add_argument("--benchmark", action="store_true", help="Run all patterns on all scenarios")
    parser.add_argument("--output", type=Path, help="Benchmark CSV output path inside BTVN03")
    parser.add_argument("--repeats", type=int, default=1, help="Benchmark repetitions (default: 1)")
    parser.add_argument("--self-test", action="store_true", help="Run deterministic self-tests")
    parser.add_argument("--approve-payment", action="store_true", help="Simulate explicit human approval for payment")
    parser.add_argument(
        "--model-mode",
        choices=("deterministic", "langchain"),
        default="deterministic",
        help="deterministic for repeatable benchmark; langchain for live Gemini runs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.benchmark:
        if args.repeats < 1:
            print("--repeats must be at least 1", file=sys.stderr)
            return 2
        if args.output and not args.output.resolve().is_relative_to(PROJECT_DIR):
            print("--output must stay inside BTVN03", file=sys.stderr)
            return 2
        output = args.output or PROJECT_DIR / ("results_gemini.csv" if args.model_mode == "langchain" else "results.csv")
        try:
            rows = benchmark(args.repeats, model_mode=args.model_mode, output=output)
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 2
        print_benchmark_summary(rows, output)
        return 0
    if not args.pattern:
        print("Choose --pattern ... or --benchmark or --self-test", file=sys.stderr)
        return 2
    try:
        state = run_pattern(
            args.pattern,
            args.scenario,
            human_payment_approval=args.approve_payment,
            model_mode=args.model_mode,
        )
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    render_trace(state)
    return 0 if state.termination_reason in {TerminationReason.SUCCESS, TerminationReason.NEED_HUMAN} else 1


if __name__ == "__main__":
    raise SystemExit(main())
