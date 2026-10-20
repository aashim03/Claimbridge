"""Worker skeleton shared by every agent.

    loop: heartbeat -> claim lease -> resume checkpoint -> work -> fenced commit

A worker keeps nothing between steps. Everything it needs is read from the graph
and everything it produces is written back, so any replica can pick up any claim.
"""
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field

from claimbridge import config, db
from claimbridge.tools import Owner
from claimbridge.tools import coordination as coord

log = logging.getLogger("claimbridge.worker")


class Recoverable(Exception):
    """Release the lease and let any worker retry."""


class NeedsHuman(Exception):
    """Stop automation for this claim."""


@dataclass
class Context:
    g: object
    claim_id: str
    me: str
    attempt: int
    checkpoint: dict | None              # intermediate state left by a previous owner
    resumed_from: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    payload: dict
    checkpoint: dict = field(default_factory=dict)
    next_state: str | None = None        # default: the worker's output_state


class Worker:
    role: str = "worker"
    input_state: str = ""
    output_state: str = ""

    def __init__(self, agent_id: str | None = None, crash_at: str | None = None,
                 step_delay_s: float | None = None, lease_ttl_s: float | None = None):
        self.me = agent_id or f"{self.role}-{socket.gethostname()}-{os.getpid()}"
        self.crash_at = crash_at
        self.step_delay_s = config.STEP_DELAY_S if step_delay_s is None else step_delay_s
        self.lease_ttl_s = config.LEASE_TTL_S if lease_ttl_s is None else lease_ttl_s
        self.g = db.connect()
        self._stop = threading.Event()

    # ---- hooks for agents -------------------------------------------------
    def work(self, ctx: Context) -> StepResult:
        raise NotImplementedError

    def maybe_crash(self, point: str):
        """Simulate a hard crash (no cleanup, lease left dangling) for demos and tests."""
        if self.crash_at == point:
            log.warning("%s: simulated crash at %s", self.me, point)
            os._exit(137)

    def pause(self):
        """Demo pacing: makes each step long enough to watch (and to kill)."""
        if self.step_delay_s:
            time.sleep(self.step_delay_s)

    # ---- loop ---------------------------------------------------------------
    def shutdown_requested(self) -> bool:
        r = db.one(self.g, "MATCH (s:Control {id: 'global'}) RETURN s.shutdown_at AS t")
        return bool(r and r["t"] and r["t"] >= self.started_at)

    def run(self, exit_when_idle: bool = False, max_steps: int | None = None) -> int:
        steps = 0
        self.started_at = db.now_ms()
        coord.heartbeat(self.g, self.me, self.role, "idle")
        while not self._stop.is_set():
            if self.shutdown_requested():
                break
            coord.heartbeat(self.g, self.me, self.role, "idle")
            if self.step_once():
                steps += 1
                if max_steps and steps >= max_steps:
                    break
            elif exit_when_idle:
                break
            else:
                time.sleep(config.POLL_S)
        coord.heartbeat(self.g, self.me, self.role, "stopped")
        return steps

    def step_once(self) -> bool:
        lease = coord.claim_lease(self.g, self.input_state, self.me, ttl_s=self.lease_ttl_s)
        if not lease:
            return False
        cid, attempt = lease["claim_id"], lease["attempt"]
        # This acquisition's identity: our agent id plus the lease generation (fencing token).
        me = Owner(self.me, lease["gen"])
        coord.heartbeat(self.g, self.me, self.role, "working", cid)

        if attempt > config.MAX_ATTEMPTS:
            coord.commit(self.g, cid, me, self.role, self.input_state, "NEEDS_HUMAN",
                         "GAVE_UP", {"attempts": attempt - 1})
            return True

        cp = coord.load_checkpoint(self.g, cid, self.input_state)
        if cp and cp.get("_complete"):
            cp = None  # a completed checkpoint belongs to an earlier, finished pass
        prev = lease.get("prev_owner")
        if attempt > 1:
            coord.append_event(self.g, cid, "RESUMED", self.me, self.role, self.input_state,
                               {"attempt": attempt, "previous_owner": prev,
                                "checkpoint_from": cp.get("_agent_id") if cp else None},
                               me=me)
        else:
            coord.append_event(self.g, cid, "CLAIMED", self.me, self.role, self.input_state,
                               {"attempt": attempt}, me=me)

        ctx = Context(self.g, cid, me, attempt, cp, resumed_from=prev)
        hb = _LeaseKeeper(cid, me)
        hb.start()
        try:
            result = self.work(ctx)
            self.pause()
            self.maybe_crash("before_commit")
            ok = coord.commit(self.g, cid, me, self.role, self.input_state,
                              result.next_state or self.output_state,
                              f"{self.role.upper()}_DONE", result.payload, result.checkpoint)
            if not ok:
                log.warning("%s: fenced out of %s (lease lost)", self.me, cid)
                coord.append_event(self.g, cid, "FENCED_WRITE_REJECTED", self.me, self.role,
                                   self.input_state, {"attempt": attempt})
            return True
        except NeedsHuman as e:
            coord.commit(self.g, cid, me, self.role, self.input_state, "NEEDS_HUMAN",
                         "NEEDS_HUMAN", {"reason": str(e)})
            return True
        except Recoverable as e:
            log.warning("%s: recoverable failure on %s: %s", self.me, cid, e)
            coord.release(self.g, cid, me)
            return True
        finally:
            hb.stop()
            coord.heartbeat(self.g, self.me, self.role, "idle")


class _LeaseKeeper(threading.Thread):
    """Extends the lease every HEARTBEAT_S while a step runs (its own connection)."""

    def __init__(self, cid: str, me: str):
        super().__init__(daemon=True)
        self.cid, self.me = cid, me
        self._halt = threading.Event()
        self.lost = False

    def run(self):
        g = db.connect()
        while not self._halt.wait(config.HEARTBEAT_S):
            if not coord.extend_lease(g, self.cid, self.me):
                self.lost = True
                return

    def stop(self):
        self._halt.set()
