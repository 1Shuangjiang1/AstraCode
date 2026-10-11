import threading
import time
import unittest

from agent_harness.concurrency import WorkspaceCoordinator


class WorkspaceCoordinatorTests(unittest.TestCase):
    def test_only_one_actor_enters_workspace_at_a_time(self):
        coordinator = WorkspaceCoordinator()
        state_lock = threading.Lock()
        active = 0
        maximum = 0

        def worker(name):
            nonlocal active, maximum
            with coordinator.access(name, "test"):
                with state_lock:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.04)
                with state_lock:
                    active -= 1

        threads = [threading.Thread(target=worker, args=(f"agent-{index}",)) for index in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(maximum, 1)
        self.assertEqual(coordinator.snapshot()["waiting"], 0)


if __name__ == "__main__":
    unittest.main()

