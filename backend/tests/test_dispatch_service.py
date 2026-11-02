import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.dispatch_service import DispatchService


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, s): self.t += s


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.clk = Clock()
        self.owner, self.fd = [], []
        self.db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        self.svc = DispatchService(self.db, self.owner.append, lambda t, p=None: self.fd.append(t),
                                   countdown_s=30, rearm_after_cancel_s=120, reset_after_normal_s=300, clock=self.clk)

    def tearDown(self): os.unlink(self.db)

    def feed(self, state, secs=1, ack=0, n=1):
        out = None
        for _ in range(n):
            self.clk.adv(secs)
            r = self.svc.on_reading("dev1", state, 80, ack_seq=ack, context={"room": "Lab 3"})
            out = r or out
        return out

    def test_no_dispatch_below_fire_confirmed(self):
        self.feed("PRECURSOR", n=60); self.feed("CONFIRMING", n=60)
        self.assertEqual(self.fd, []); self.assertEqual(self.svc.status("dev1")["phase"], "idle")

    def test_countdown_then_simulated_dispatch(self):
        self.feed("FIRE_CONFIRMED")
        self.assertEqual(self.svc.status("dev1")["phase"], "pending")
        self.feed("FIRE_CONFIRMED", n=28); self.assertEqual(self.fd, [])
        self.feed("FIRE_CONFIRMED", n=3)
        self.assertEqual(len(self.fd), 1)
        self.assertIn("SIMULATION", self.fd[0]); self.assertIn("Lab 3", self.fd[0])
        self.assertEqual(self.svc.events()[0]["event_type"], "dispatched_sim")

    def test_device_ack_cancels(self):
        self.feed("FIRE_CONFIRMED", ack=0)
        self.feed("FIRE_CONFIRMED", ack=0, n=5)
        self.assertEqual(self.feed("FIRE_CONFIRMED", ack=1), "cancelled")
        self.feed("FIRE_CONFIRMED", ack=1, n=60)           # still the same episode, within re-arm window
        self.assertEqual(self.fd, [])

    def test_rearm_when_fire_persists_after_cancel(self):
        self.feed("FIRE_CONFIRMED", ack=0); self.feed("FIRE_CONFIRMED", ack=1)
        self.assertEqual(self.svc.status("dev1")["phase"], "cancelled")
        self.feed("FIRE_CONFIRMED", ack=1, n=125)
        self.assertEqual(self.svc.status("dev1")["phase"], "pending")
        self.feed("FIRE_CONFIRMED", ack=1, n=31)           # old ack must not cancel again
        self.assertEqual(len(self.fd), 1)

    def test_second_button_press_cancels_rearmed_countdown(self):
        self.feed("FIRE_CONFIRMED", ack=0); self.feed("FIRE_CONFIRMED", ack=1)
        self.feed("FIRE_CONFIRMED", ack=1, n=125)
        self.assertEqual(self.feed("FIRE_CONFIRMED", ack=2), "cancelled")

    def test_dashboard_cancel(self):
        self.feed("FIRE_CONFIRMED"); self.assertTrue(self.svc.cancel("dev1", "dashboard"))
        self.assertFalse(self.svc.cancel("dev1"))

    def test_auto_clear_when_state_drops(self):
        self.feed("FIRE_CONFIRMED"); self.assertEqual(self.feed("PRECURSOR"), "auto_cleared"); self.assertEqual(self.fd, [])

    def test_tick_dispatches_when_device_goes_silent(self):
        self.feed("FIRE_CONFIRMED"); self.clk.adv(31); self.svc.tick()
        self.assertEqual(len(self.fd), 1)

    def test_reset_after_calm_allows_new_episode(self):
        self.feed("FIRE_CONFIRMED"); self.clk.adv(31); self.svc.tick()
        self.feed("NORMAL", n=301); self.assertEqual(self.svc.status("dev1")["phase"], "idle")
        self.feed("FIRE_CONFIRMED"); self.assertEqual(self.svc.status("dev1")["phase"], "pending")

    def test_telegram_failure_does_not_break_pipeline(self):
        def boom(*_): raise RuntimeError("telegram down")
        svc = DispatchService(self.db, boom, boom, clock=self.clk)
        self.clk.adv(1); svc.on_reading("x", "FIRE_CONFIRMED", 90, ack_seq=0)
        self.clk.adv(31); svc.tick()
        self.assertEqual(svc.status("x")["phase"], "dispatched")

    def test_device_reboot_reseeds_ack_counter(self):
        self.feed("NORMAL", ack=5); self.feed("FIRE_CONFIRMED", ack=0)     # reboot: counter went 5 -> 0
        self.assertEqual(self.svc.status("dev1")["phase"], "pending")      # not mistaken for an ack


if __name__ == "__main__":
    unittest.main(verbosity=2)
