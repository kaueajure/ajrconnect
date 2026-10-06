"""Bounded retry policy for transport failures, independent of GTK and secrets."""
from dataclasses import dataclass

# FreeRDP 2.11.5 XF_EXIT_CODE: transport/connect/DNS failures only.
NETWORK_EXIT_CODES = frozenset((131, 137, 139, 140, 141, 147))


@dataclass
class RetryPlan:
    enabled: bool = True
    attempts: int = 0
    cancelled: bool = False
    delays: tuple = (2, 4, 8, 16, 30)

    def next_delay(self):
        if not self.enabled or self.cancelled or self.attempts >= len(self.delays):
            return None
        delay = self.delays[self.attempts]
        self.attempts += 1
        return delay

    def should_retry(self, code, *, connected=False, recovering=False):
        return self.enabled and not self.cancelled and (connected or recovering) \
            and code in NETWORK_EXIT_CODES

    def reset(self):
        self.attempts = 0

    def cancel(self):
        self.cancelled = True
