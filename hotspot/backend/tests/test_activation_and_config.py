import json
import os
import tempfile
import unittest

from routes import activation, mouse_config
from utils.activation_state_store import merge_states


class ActivationAndConfigContractTests(unittest.TestCase):
    def test_activation_flag_coerce_contract(self):
        self.assertTrue(activation._coerce_activated_flag(True))
        self.assertTrue(activation._coerce_activated_flag("true"))
        self.assertTrue(activation._coerce_activated_flag("1"))
        self.assertFalse(activation._coerce_activated_flag(False))
        self.assertFalse(activation._coerce_activated_flag("false"))
        self.assertFalse(activation._coerce_activated_flag("0"))
        self.assertFalse(activation._coerce_activated_flag(None))

    def test_activation_save_uses_secure_store_and_loads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_file = activation.ACTIVATION_FILE
            old_save_secure = activation.save_secure_state
            old_load_secure = activation.load_secure_state
            captured = {}
            try:
                activation.ACTIVATION_FILE = os.path.join(tmp, "activation.json")
                activation.save_secure_state = lambda payload: captured.update(payload) or True
                activation.load_secure_state = lambda: dict(captured)
                payload = {"activated": False, "uuid": "u", "license_blob": ""}
                self.assertTrue(activation.save_activation_status(payload))
                loaded = activation.load_activation_status()
                self.assertIn("activated", loaded)
                self.assertFalse(loaded.get("activated"))
                self.assertFalse(os.path.exists(activation.ACTIVATION_FILE))
            finally:
                activation.ACTIVATION_FILE = old_file
                activation.save_secure_state = old_save_secure
                activation.load_secure_state = old_load_secure

    def test_secure_state_merge_is_conservative_for_trial_history(self):
        merged = merge_states(
            [
                {
                    "trial_explicit_started": False,
                    "trial_started_at": None,
                    "license_ever_activated": False,
                    "clock_rollback_detected": False,
                    "updated_at": 20,
                },
                {
                    "trial_explicit_started": True,
                    "trial_started_at": 100,
                    "license_ever_activated": True,
                    "clock_rollback_detected": True,
                    "updated_at": 10,
                },
            ]
        )
        self.assertTrue(merged["trial_explicit_started"])
        self.assertEqual(merged["trial_started_at"], 100)
        self.assertTrue(merged["license_ever_activated"])
        self.assertTrue(merged["clock_rollback_detected"])

    def test_secure_state_merge_keeps_latest_activation_choice(self):
        merged = merge_states(
            [
                {"activated": True, "license_blob": "old", "updated_at": 10},
                {"activated": False, "license_blob": "", "updated_at": 20},
            ]
        )
        self.assertFalse(merged["activated"])
        self.assertEqual(merged["license_blob"], "")

    def test_mouse_buttons_data_repair_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = mouse_config.DATA_DIR
            old_json = mouse_config.JSON_FILE
            try:
                mouse_config.DATA_DIR = tmp
                mouse_config.JSON_FILE = os.path.join(tmp, "mouse_buttons.json")
                with open(mouse_config.JSON_FILE, "w", encoding="utf-8") as f:
                    json.dump({"buttons": ["bad", {"id": "ok", "action": "ctrl+c"}]}, f, ensure_ascii=False)
                repaired = mouse_config.load_buttons_data()
                self.assertIsInstance(repaired.get("buttons"), list)
                self.assertEqual(len(repaired["buttons"]), 1)
                self.assertEqual(repaired["buttons"][0]["id"], "ok")
            finally:
                mouse_config.DATA_DIR = old_dir
                mouse_config.JSON_FILE = old_json


if __name__ == "__main__":
    unittest.main()
